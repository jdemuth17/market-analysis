using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using Microsoft.Extensions.Logging;

namespace MarketAnalysis.Infrastructure.Services;

public class DailyScanService : IDailyScanService
{
    private readonly IUserScanConfigRepository _configRepo;
    private readonly IIndexDefinitionRepository _indexRepo;
    private readonly IWatchListRepository _watchListRepo;
    private readonly IPythonServiceClient _python;
    private readonly IMarketDataIngestionService _ingestion;
    private readonly IReportGenerationService _reportGen;
    private readonly IScanProgressTracker _progress;
    private readonly ILogger<DailyScanService> _logger;

    public DailyScanService(
        IUserScanConfigRepository configRepo,
        IIndexDefinitionRepository indexRepo,
        IWatchListRepository watchListRepo,
        IPythonServiceClient python,
        IMarketDataIngestionService ingestion,
        IReportGenerationService reportGen,
        IScanProgressTracker progress,
        ILogger<DailyScanService> logger)
    {
        _configRepo = configRepo;
        _indexRepo = indexRepo;
        _watchListRepo = watchListRepo;
        _python = python;
        _ingestion = ingestion;
        _reportGen = reportGen;
        _progress = progress;
        _logger = logger;
    }

    public async Task RunFullScanAsync(CancellationToken cancellationToken = default)
    {
        if (_progress.IsRunning)
        {
            _logger.LogWarning("A scan is already running, skipping");
            return;
        }

        _logger.LogInformation("=== Daily Scan Pipeline Started ===");
        var sw = System.Diagnostics.Stopwatch.StartNew();

        try
        {
            // 1. Load config
            var config = await _configRepo.GetDefaultAsync()
                ?? throw new InvalidOperationException("No default scan configuration found");

            _logger.LogInformation("Using config: {Name}", config.Name);

            // 2. Build ticker universe
            var tickers = await BuildTickerUniverseAsync();
            if (tickers.Count == 0)
            {
                _logger.LogWarning("No tickers to scan. Configure watchlists or enable index scans.");
                return;
            }

            _logger.LogInformation("Scanning {Count} tickers", tickers.Count);
            _progress.Start(tickers.Count, totalSteps: 6);

            // 3. Health check
            if (!await _python.HealthCheckAsync())
            {
                _progress.Fail("Python service is not available");
                _logger.LogError("Python service is not available. Aborting scan.");
                return;
            }

            // Step 1: Pre-filter by price & volume
            cancellationToken.ThrowIfCancellationRequested();
            _progress.SetStep(1, "Pre-filtering by price & volume...");
            _logger.LogInformation("Step 1/6: Pre-filtering by price & volume...");
            tickers = await PreFilterTickersAsync(tickers, config);

            if (tickers.Count == 0)
            {
                _logger.LogWarning("No tickers passed pre-filter criteria.");
                _progress.Complete();
                return;
            }

            // Update progress with filtered ticker count
            _progress.Start(tickers.Count, totalSteps: 6);

            // Step 2: Ingest price data
            cancellationToken.ThrowIfCancellationRequested();
            _progress.SetStep(2, "Ingesting price data...");
            _logger.LogInformation("Step 2/6: Ingesting price data...");
            await _ingestion.IngestPriceDataAsync(tickers);

            // Step 3: Ingest fundamentals
            cancellationToken.ThrowIfCancellationRequested();
            _progress.SetStep(3, "Ingesting fundamentals...");
            _logger.LogInformation("Step 3/6: Ingesting fundamentals...");
            await _ingestion.IngestFundamentalsAsync(tickers);

            // Step 4: Run technical analysis
            cancellationToken.ThrowIfCancellationRequested();
            _progress.SetStep(4, "Running technical analysis...");
            _logger.LogInformation("Step 4/6: Running technical analysis...");
            await _ingestion.IngestTechnicalsAsync(tickers, config);

            // Step 5: Run sentiment analysis
            cancellationToken.ThrowIfCancellationRequested();
            _progress.SetStep(5, "Running sentiment analysis...");
            _logger.LogInformation("Step 5/6: Running sentiment analysis...");
            await _ingestion.IngestSentimentAsync(tickers, config);

            // Step 6: Generate reports
            cancellationToken.ThrowIfCancellationRequested();
            _progress.SetStep(6, "Generating reports...");
            _logger.LogInformation("Step 6/6: Generating reports...");
            var reportDate = DateOnly.FromDateTime(DateTime.UtcNow);
            var reports = await _reportGen.GenerateReportsAsync(config, reportDate);

            sw.Stop();
            _progress.Complete();
            _logger.LogInformation(
                "=== Daily Scan Complete === {ReportCount} reports generated in {Elapsed:F1}s",
                reports.Count, sw.Elapsed.TotalSeconds);
        }
        catch (OperationCanceledException)
        {
            _progress.Fail("Scan was cancelled");
            _logger.LogWarning("Daily scan was cancelled");
            throw;
        }
        catch (Exception ex)
        {
            _progress.Fail(ex.Message);
            _logger.LogError(ex, "Daily scan failed");
            throw;
        }
    }

    private async Task<List<string>> PreFilterTickersAsync(List<string> tickers, UserScanConfig config)
    {
        if (!config.PriceRangeMin.HasValue && !config.PriceRangeMax.HasValue && !config.MinDailyVolume.HasValue)
        {
            _logger.LogInformation("No pre-filters configured, scanning all {Count} tickers", tickers.Count);
            return tickers;
        }

        _logger.LogInformation(
            "Pre-filtering {Count} tickers (price: {Min}-{Max}, min volume: {Vol})",
            tickers.Count, config.PriceRangeMin, config.PriceRangeMax, config.MinDailyVolume);

        var passed = new List<string>();

        foreach (var batch in tickers.Chunk(50))
        {
            try
            {
                var response = await _python.FetchPricesAsync(batch.ToList(), period: "5d", interval: "1d");

                foreach (var tickerData in response.Data.Where(d => d.Error is null))
                {
                    if (!tickerData.Bars.Any()) continue;

                    var latestBar = tickerData.Bars.OrderByDescending(b => b.Date).First();
                    var avgVolume = (long)tickerData.Bars.Average(b => b.Volume);

                    if (config.PriceRangeMin.HasValue && latestBar.Close < config.PriceRangeMin.Value)
                        continue;
                    if (config.PriceRangeMax.HasValue && latestBar.Close > config.PriceRangeMax.Value)
                        continue;
                    if (config.MinDailyVolume.HasValue && avgVolume < config.MinDailyVolume.Value)
                        continue;

                    passed.Add(tickerData.Ticker);
                }

                // Increment per ticker in the batch (not once per batch)
                foreach (var _ in batch) _progress.IncrementTicker();
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Pre-filter fetch failed for batch, including all tickers");
                passed.AddRange(batch);
                foreach (var _ in batch) _progress.IncrementTicker();
            }
        }

        _logger.LogInformation("Pre-filter: {Passed}/{Total} tickers passed", passed.Count, tickers.Count);
        return passed;
    }

    private async Task<List<string>> BuildTickerUniverseAsync()
    {
        var tickers = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        // Add tickers from watchlists
        var watchLists = await _watchListRepo.GetAllWithItemCountAsync();
        foreach (var wl in watchLists)
        {
            var full = await _watchListRepo.GetWithItemsAsync(wl.Id);
            if (full?.Items is not null)
            {
                foreach (var item in full.Items)
                    tickers.Add(item.Stock.Ticker);
            }
        }

        // Add tickers from enabled indexes
        var enabledIndexes = await _indexRepo.GetEnabledAsync();
        foreach (var idx in enabledIndexes)
        {
            if (idx.Tickers.Length > 0)
            {
                foreach (var t in idx.Tickers) tickers.Add(t);
            }
            else
            {
                // Fetch from Python service
                try
                {
                    var indexTickers = await _python.GetTickerListAsync(idx.Name);
                    foreach (var t in indexTickers) tickers.Add(t);

                    // Cache the tickers
                    idx.Tickers = indexTickers.ToArray();
                    idx.LastRefreshedUtc = DateTime.UtcNow;
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Failed to fetch tickers for index {Name}", idx.Name);
                }
            }
        }

        return tickers.ToList();
    }
}
