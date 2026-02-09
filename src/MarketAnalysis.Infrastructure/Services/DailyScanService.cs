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
    private readonly ILogger<DailyScanService> _logger;

    public DailyScanService(
        IUserScanConfigRepository configRepo,
        IIndexDefinitionRepository indexRepo,
        IWatchListRepository watchListRepo,
        IPythonServiceClient python,
        IMarketDataIngestionService ingestion,
        IReportGenerationService reportGen,
        ILogger<DailyScanService> logger)
    {
        _configRepo = configRepo;
        _indexRepo = indexRepo;
        _watchListRepo = watchListRepo;
        _python = python;
        _ingestion = ingestion;
        _reportGen = reportGen;
        _logger = logger;
    }

    public async Task RunFullScanAsync(CancellationToken cancellationToken = default)
    {
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

            // 3. Health check
            if (!await _python.HealthCheckAsync())
            {
                _logger.LogError("Python service is not available. Aborting scan.");
                return;
            }

            // 4. Ingest price data
            cancellationToken.ThrowIfCancellationRequested();
            _logger.LogInformation("Step 1/5: Ingesting price data...");
            await _ingestion.IngestPriceDataAsync(tickers);

            // 5. Ingest fundamentals
            cancellationToken.ThrowIfCancellationRequested();
            _logger.LogInformation("Step 2/5: Ingesting fundamentals...");
            await _ingestion.IngestFundamentalsAsync(tickers);

            // 6. Run technical analysis
            cancellationToken.ThrowIfCancellationRequested();
            _logger.LogInformation("Step 3/5: Running technical analysis...");
            await _ingestion.IngestTechnicalsAsync(tickers, config);

            // 7. Run sentiment analysis
            cancellationToken.ThrowIfCancellationRequested();
            _logger.LogInformation("Step 4/5: Running sentiment analysis...");
            await _ingestion.IngestSentimentAsync(tickers, config);

            // 8. Generate reports
            cancellationToken.ThrowIfCancellationRequested();
            _logger.LogInformation("Step 5/5: Generating reports...");
            var reportDate = DateOnly.FromDateTime(DateTime.UtcNow);
            var reports = await _reportGen.GenerateReportsAsync(config, reportDate);

            sw.Stop();
            _logger.LogInformation(
                "=== Daily Scan Complete === {ReportCount} reports generated in {Elapsed:F1}s",
                reports.Count, sw.Elapsed.TotalSeconds);
        }
        catch (OperationCanceledException)
        {
            _logger.LogWarning("Daily scan was cancelled");
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Daily scan failed");
            throw;
        }
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
