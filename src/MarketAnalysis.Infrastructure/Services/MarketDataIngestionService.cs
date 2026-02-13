using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Enums;
using MarketAnalysis.Core.Interfaces;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace MarketAnalysis.Infrastructure.Services;

public class MarketDataIngestionService : IMarketDataIngestionService
{
    private readonly IPythonServiceClient _python;
    private readonly IStockRepository _stockRepo;
    private readonly IPriceHistoryRepository _priceRepo;
    private readonly IFundamentalRepository _fundamentalRepo;
    private readonly ITechnicalSignalRepository _technicalRepo;
    private readonly ISentimentRepository _sentimentRepo;
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IScanProgressTracker _progress;
    private readonly ILogger<MarketDataIngestionService> _logger;

    public MarketDataIngestionService(
        IPythonServiceClient python,
        IStockRepository stockRepo,
        IPriceHistoryRepository priceRepo,
        IFundamentalRepository fundamentalRepo,
        ITechnicalSignalRepository technicalRepo,
        ISentimentRepository sentimentRepo,
        IServiceScopeFactory scopeFactory,
        IScanProgressTracker progress,
        ILogger<MarketDataIngestionService> logger)
    {
        _python = python;
        _stockRepo = stockRepo;
        _priceRepo = priceRepo;
        _fundamentalRepo = fundamentalRepo;
        _technicalRepo = technicalRepo;
        _sentimentRepo = sentimentRepo;
        _scopeFactory = scopeFactory;
        _progress = progress;
        _logger = logger;
    }

    public async Task IngestPriceDataAsync(List<string> tickers, string period = "6mo")
    {
        _logger.LogInformation("Ingesting price data for {Count} tickers", tickers.Count);

        // --- Incremental: determine which tickers need full vs partial fetch ---
        var today = DateOnly.FromDateTime(DateTime.UtcNow);
        var allStocks = await _stockRepo.GetByTickersAsync(tickers);
        var stockIds = allStocks.Select(s => s.Id).ToList();
        var latestPrices = stockIds.Count > 0
            ? await _priceRepo.GetLatestForStocksAsync(stockIds)
            : new Dictionary<int, PriceHistory>();

        var freshLookup = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var recentLookup = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var stock in allStocks)
        {
            if (latestPrices.TryGetValue(stock.Id, out var latest))
            {
                var age = today.DayNumber - latest.Date.DayNumber;
                if (age <= 3) freshLookup.Add(stock.Ticker);      // Have very recent data → 5d only
                else if (age <= 14) recentLookup.Add(stock.Ticker); // Moderately stale → 1mo
                // else: stale → full 6mo
            }
        }

        var freshTickers = tickers.Where(t => freshLookup.Contains(t)).ToList();
        var recentTickers = tickers.Where(t => recentLookup.Contains(t)).ToList();
        var staleTickers = tickers.Where(t => !freshLookup.Contains(t) && !recentLookup.Contains(t)).ToList();

        _logger.LogInformation(
            "Price fetch split: {Fresh} fresh (5d), {Recent} recent (1mo), {Stale} stale (6mo)",
            freshTickers.Count, recentTickers.Count, staleTickers.Count);

        // Process each group with the appropriate period
        await IngestPriceBatchesAsync(freshTickers, "5d");
        await IngestPriceBatchesAsync(recentTickers, "1mo");
        await IngestPriceBatchesAsync(staleTickers, period);
    }

    private async Task IngestPriceBatchesAsync(List<string> tickers, string period)
    {
        if (tickers.Count == 0) return;

        // Fetch in batches of 50
        foreach (var batch in tickers.Chunk(50))
        {
            try
            {
                var response = await _python.FetchPricesAsync(batch.ToList(), period);

                foreach (var tickerData in response.Data.Where(d => d.Error is null))
                {
                    try
                    {
                        var stock = await _stockRepo.GetOrCreateAsync(tickerData.Ticker);
                        var prices = tickerData.Bars.Select(b => new PriceHistory
                        {
                            StockId = stock.Id,
                            Date = b.Date,
                            Open = b.Open,
                            High = b.High,
                            Low = b.Low,
                            Close = b.Close,
                            AdjClose = b.AdjClose,
                            Volume = b.Volume,
                        }).ToList();

                        await _priceRepo.UpsertRangeAsync(stock.Id, prices);
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "Price upsert failed for {Ticker}", tickerData.Ticker);
                    }
                    finally
                    {
                        _progress.IncrementTicker();
                    }
                }

                _logger.LogInformation("Batch prices ({Period}) ingested: {Ok}/{Total}",
                    period, response.Successful, response.TotalTickers);
            }
            catch (HttpRequestException httpEx)
            {
                _logger.LogWarning(httpEx, "Price fetch HTTP error for batch: {Status}", httpEx.StatusCode);
                foreach (var _ in batch) _progress.IncrementTicker();
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Price fetch failed for batch: {Message}", ex.Message);
                foreach (var _ in batch) _progress.IncrementTicker();
            }
        }
    }

    public async Task IngestFundamentalsAsync(List<string> tickers)
    {
        _logger.LogInformation("Ingesting fundamentals for {Count} tickers", tickers.Count);

        // --- Incremental: skip tickers that already have today's fundamentals ---
        var today = DateOnly.FromDateTime(DateTime.UtcNow);
        var allStocks = await _stockRepo.GetByTickersAsync(tickers);
        var stockIds = allStocks.Select(s => s.Id).ToList();
        var latestFundamentals = stockIds.Count > 0
            ? await _fundamentalRepo.GetLatestForStocksAsync(stockIds)
            : new Dictionary<int, FundamentalSnapshot>();

        var alreadyDoneToday = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var stock in allStocks)
        {
            if (latestFundamentals.TryGetValue(stock.Id, out var snap) && snap.SnapshotDate == today)
                alreadyDoneToday.Add(stock.Ticker);
        }

        var tickersToFetch = tickers.Where(t => !alreadyDoneToday.Contains(t)).ToList();
        var skipped = tickers.Count - tickersToFetch.Count;

        if (skipped > 0)
        {
            _logger.LogInformation(
                "Fundamentals: skipping {Skipped} tickers already updated today, fetching {Remaining}",
                skipped, tickersToFetch.Count);
            // Increment progress for skipped tickers
            for (int i = 0; i < skipped; i++) _progress.IncrementTicker();
        }

        if (tickersToFetch.Count == 0) return;

        foreach (var batch in tickersToFetch.Chunk(50))
        {
            try
            {
                var response = await _python.FetchFundamentalsAsync(batch.ToList());
                var validData = response.Data.Where(d => d.Error is null).ToList();

                // Score all fundamentals in one batch HTTP call instead of N individual calls
                Dictionary<string, FundamentalScoreDto> scoreMap = new();
                if (validData.Count > 0)
                {
                    try
                    {
                        var batchScores = await _python.ScoreFundamentalsBatchAsync(validData);
                        foreach (var s in batchScores.Scores)
                            scoreMap[s.Ticker] = s;
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "Batch scoring failed, using defaults");
                    }
                }

                foreach (var fd in validData)
                {
                    try
                    {
                        var stock = await _stockRepo.GetOrCreateAsync(fd.Ticker, fd.CompanyName);

                        // Update stock metadata
                        stock.Sector = fd.Sector;
                        stock.Industry = fd.Industry;
                        stock.Exchange = fd.Exchange;
                        stock.MarketCap = fd.MarketCap.HasValue ? (decimal)fd.MarketCap.Value : null;
                        stock.LastUpdatedUtc = DateTime.UtcNow;
                        await _stockRepo.UpdateAsync(stock);

                        // Use batch score if available, otherwise default
                        var score = scoreMap.TryGetValue(fd.Ticker, out var s) ? s
                            : new FundamentalScoreDto(fd.Ticker, 50, 50, 50, 50, 50);

                        var snapshot = new FundamentalSnapshot
                        {
                            StockId = stock.Id,
                            SnapshotDate = DateOnly.FromDateTime(DateTime.UtcNow),
                            PeRatio = fd.PeRatio,
                            ForwardPe = fd.ForwardPe,
                            PegRatio = fd.PegRatio,
                            PriceToBook = fd.PriceToBook,
                            DebtToEquity = fd.DebtToEquity,
                            ProfitMargin = fd.ProfitMargin,
                            OperatingMargin = fd.OperatingMargin,
                            ReturnOnEquity = fd.ReturnOnEquity,
                            FreeCashFlow = fd.FreeCashFlow.HasValue ? (decimal)fd.FreeCashFlow.Value : null,
                            DividendYield = fd.DividendYield,
                            Revenue = fd.Revenue.HasValue ? (decimal)fd.Revenue.Value : null,
                            MarketCap = fd.MarketCap.HasValue ? (decimal)fd.MarketCap.Value : null,
                            Beta = fd.Beta,
                            FiftyTwoWeekHigh = fd.FiftyTwoWeekHigh.HasValue ? (decimal)fd.FiftyTwoWeekHigh.Value : null,
                            FiftyTwoWeekLow = fd.FiftyTwoWeekLow.HasValue ? (decimal)fd.FiftyTwoWeekLow.Value : null,
                            CurrentPrice = fd.CurrentPrice.HasValue ? (decimal)fd.CurrentPrice.Value : null,
                            TargetMeanPrice = fd.TargetMeanPrice.HasValue ? (decimal)fd.TargetMeanPrice.Value : null,
                            RecommendationKey = fd.RecommendationKey,
                            ValueScore = score.ValueScore,
                            QualityScore = score.QualityScore,
                            GrowthScore = score.GrowthScore,
                            SafetyScore = score.SafetyScore,
                            CompositeScore = score.CompositeScore,
                            RawData = System.Text.Json.JsonSerializer.Serialize(fd),
                        };

                        await _fundamentalRepo.AddAsync(snapshot);
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "Fundamental ingestion failed for {Ticker}", fd.Ticker);
                    }
                    finally
                    {
                        _progress.IncrementTicker();
                    }
                }

                // Increment progress for failed tickers too
                foreach (var fd in response.Data.Where(d => d.Error is not null))
                    _progress.IncrementTicker();
            }
            catch (HttpRequestException httpEx)
            {
                _logger.LogWarning(httpEx, "Fundamentals fetch HTTP error for batch: {Status}", httpEx.StatusCode);
                foreach (var _ in batch) _progress.IncrementTicker();
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Fundamentals fetch failed for batch: {Message}", ex.Message);
                foreach (var _ in batch) _progress.IncrementTicker();
            }
        }
    }

    public async Task IngestTechnicalsAsync(List<string> tickers, UserScanConfig config)
    {
        _logger.LogInformation("Ingesting technicals for {Count} tickers (10 parallel)", tickers.Count);
        var today = DateOnly.FromDateTime(DateTime.UtcNow);

        // --- Incremental: skip tickers that already have signals for today ---
        var todaySignals = await _technicalRepo.GetByDateAsync(today);
        var stockIdsWithSignals = new HashSet<int>(todaySignals.Select(s => s.StockId));

        var allStocks = await _stockRepo.GetByTickersAsync(tickers);
        var alreadyDoneToday = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var stock in allStocks)
        {
            if (stockIdsWithSignals.Contains(stock.Id))
                alreadyDoneToday.Add(stock.Ticker);
        }

        var tickersToAnalyze = tickers.Where(t => !alreadyDoneToday.Contains(t)).ToList();
        var skipped = tickers.Count - tickersToAnalyze.Count;

        if (skipped > 0)
        {
            _logger.LogInformation(
                "Technicals: skipping {Skipped} tickers already analyzed today, analyzing {Remaining}",
                skipped, tickersToAnalyze.Count);
            for (int i = 0; i < skipped; i++) _progress.IncrementTicker();
        }

        if (tickersToAnalyze.Count == 0) return;

        var parallelOptions = new ParallelOptions { MaxDegreeOfParallelism = 10 };

        await Parallel.ForEachAsync(tickersToAnalyze, parallelOptions, async (ticker, ct) =>
        {
            try
            {
                using var scope = _scopeFactory.CreateScope();
                var stockRepo = scope.ServiceProvider.GetRequiredService<IStockRepository>();
                var priceRepo = scope.ServiceProvider.GetRequiredService<IPriceHistoryRepository>();
                var technicalRepo = scope.ServiceProvider.GetRequiredService<ITechnicalSignalRepository>();

                var stock = await stockRepo.GetByTickerAsync(ticker);
                if (stock is null) return;

                var prices = await priceRepo.GetByStockAsync(stock.Id, 365);
                if (prices.Count < 30) return;

                var bars = prices
                    .OrderBy(p => p.Date)
                    .Select(p => new OHLCVBarDto(p.Date, p.Open, p.High, p.Low, p.Close, p.AdjClose, p.Volume))
                    .ToList();

                var analysis = await _python.RunFullTechnicalAnalysisAsync(
                    ticker, bars,
                    config.EnabledIndicators.ToList(),
                    config.EnabledPatterns.ToList());

                foreach (var pattern in analysis.DetectedPatterns)
                {
                    if (!Enum.TryParse<PatternType>(pattern.PatternType, true, out var pt)) continue;
                    if (!Enum.TryParse<SignalDirection>(pattern.Direction, true, out var dir)) continue;

                    var signal = new TechnicalSignal
                    {
                        StockId = stock.Id,
                        PatternType = pt,
                        Direction = dir,
                        Confidence = pattern.Confidence,
                        DetectedDate = today,
                        StartDate = pattern.StartDate,
                        EndDate = pattern.EndDate,
                        KeyPriceLevels = System.Text.Json.JsonSerializer.Serialize(pattern.KeyLevels),
                        Status = pattern.Status,
                        Metadata = pattern.Metadata is not null
                            ? System.Text.Json.JsonSerializer.Serialize(pattern.Metadata) : null,
                    };
                    await technicalRepo.AddAsync(signal);
                }
            }
            catch (HttpRequestException httpEx)
            {
                _logger.LogWarning(httpEx, "Technical analysis HTTP error for {Ticker}: {Status}",
                    ticker, httpEx.StatusCode);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Technical analysis failed for {Ticker}: {Message}",
                    ticker, ex.Message);
            }
            finally
            {
                _progress.IncrementTicker();
            }
        });
    }

    public async Task IngestSentimentAsync(List<string> tickers, UserScanConfig config)
    {
        _logger.LogInformation("Ingesting sentiment for {Count} tickers (batches of 100, parallel collection)", tickers.Count);
        var today = DateOnly.FromDateTime(DateTime.UtcNow);

        // --- Incremental: skip tickers that already have sentiment for today ---
        var allStocks = await _stockRepo.GetByTickersAsync(tickers);
        var stockIds = allStocks.Select(s => s.Id).ToList();
        var latestSentiment = stockIds.Count > 0
            ? await _sentimentRepo.GetLatestForStocksAsync(stockIds)
            : new Dictionary<int, List<SentimentScore>>();

        var alreadyDoneToday = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var stock in allStocks)
        {
            if (latestSentiment.TryGetValue(stock.Id, out var scores)
                && scores.Any(s => s.AnalysisDate == today))
                alreadyDoneToday.Add(stock.Ticker);
        }

        var tickersToAnalyze = tickers.Where(t => !alreadyDoneToday.Contains(t)).ToList();
        var skipped = tickers.Count - tickersToAnalyze.Count;

        if (skipped > 0)
        {
            _logger.LogInformation(
                "Sentiment: skipping {Skipped} tickers already analyzed today, analyzing {Remaining}",
                skipped, tickersToAnalyze.Count);
            for (int i = 0; i < skipped; i++) _progress.IncrementTicker();
        }

        if (tickersToAnalyze.Count == 0) return;

        // Batches of 100 tickers — each batch uses parallel collection (ThreadPoolExecutor 10)
        // + batched GPU FinBERT inference inside the Python service.
        // 100-ticker batches balance GPU throughput vs HTTP timeout risk and progress visibility.
        foreach (var batch in tickersToAnalyze.Chunk(100))
        {
            try
            {
                _logger.LogInformation("Sentiment batch: {Count} tickers", batch.Length);
                var response = await _python.RunSentimentPipelineAsync(
                    batch.ToList(), config.EnabledSentimentSources.ToList());

                foreach (var sentiment in response.Data.Where(d => d.Error is null))
                {
                    try
                    {
                        var stock = await _stockRepo.GetByTickerAsync(sentiment.Ticker);
                        if (stock is null) continue;

                        if (!Enum.TryParse<SentimentSource>(sentiment.Source, true, out var source)) continue;

                        var score = new SentimentScore
                        {
                            StockId = stock.Id,
                            Source = source,
                            AnalysisDate = today,
                            PositiveScore = sentiment.PositiveScore,
                            NegativeScore = sentiment.NegativeScore,
                            NeutralScore = sentiment.NeutralScore,
                            SampleSize = sentiment.SampleSize,
                            Headlines = System.Text.Json.JsonSerializer.Serialize(sentiment.Headlines),
                        };
                        await _sentimentRepo.AddAsync(score);
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "Sentiment persist failed for {Ticker}", sentiment.Ticker);
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Sentiment analysis failed for batch of {Count} tickers", batch.Length);
            }
            finally
            {
                foreach (var _ in batch) _progress.IncrementTicker();
            }
        }
    }
}
