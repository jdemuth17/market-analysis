using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Enums;
using MarketAnalysis.Core.Interfaces;
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
    private readonly ILogger<MarketDataIngestionService> _logger;

    public MarketDataIngestionService(
        IPythonServiceClient python,
        IStockRepository stockRepo,
        IPriceHistoryRepository priceRepo,
        IFundamentalRepository fundamentalRepo,
        ITechnicalSignalRepository technicalRepo,
        ISentimentRepository sentimentRepo,
        ILogger<MarketDataIngestionService> logger)
    {
        _python = python;
        _stockRepo = stockRepo;
        _priceRepo = priceRepo;
        _fundamentalRepo = fundamentalRepo;
        _technicalRepo = technicalRepo;
        _sentimentRepo = sentimentRepo;
        _logger = logger;
    }

    public async Task IngestPriceDataAsync(List<string> tickers, string period = "6mo")
    {
        _logger.LogInformation("Ingesting price data for {Count} tickers", tickers.Count);

        // Fetch in batches of 50
        foreach (var batch in tickers.Chunk(50))
        {
            var response = await _python.FetchPricesAsync(batch.ToList(), period);

            foreach (var tickerData in response.Data.Where(d => d.Error is null))
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

            _logger.LogInformation("Batch prices ingested: {Ok}/{Total}",
                response.Successful, response.TotalTickers);
        }
    }

    public async Task IngestFundamentalsAsync(List<string> tickers)
    {
        _logger.LogInformation("Ingesting fundamentals for {Count} tickers", tickers.Count);

        foreach (var batch in tickers.Chunk(50))
        {
            var response = await _python.FetchFundamentalsAsync(batch.ToList());

            foreach (var fd in response.Data.Where(d => d.Error is null))
            {
                var stock = await _stockRepo.GetOrCreateAsync(fd.Ticker, fd.CompanyName);

                // Update stock metadata
                stock.Sector = fd.Sector;
                stock.Industry = fd.Industry;
                stock.Exchange = fd.Exchange;
                stock.MarketCap = fd.MarketCap.HasValue ? (decimal)fd.MarketCap.Value : null;
                stock.LastUpdatedUtc = DateTime.UtcNow;
                await _stockRepo.UpdateAsync(stock);

                // Score fundamentals
                var score = await _python.ScoreFundamentalsAsync(fd);

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
        }
    }

    public async Task IngestTechnicalsAsync(List<string> tickers, UserScanConfig config)
    {
        _logger.LogInformation("Ingesting technicals for {Count} tickers", tickers.Count);
        var today = DateOnly.FromDateTime(DateTime.UtcNow);

        foreach (var ticker in tickers)
        {
            try
            {
                var stock = await _stockRepo.GetByTickerAsync(ticker);
                if (stock is null) continue;

                var prices = await _priceRepo.GetByStockAsync(stock.Id, 365);
                if (prices.Count < 30) continue;

                var bars = prices
                    .OrderBy(p => p.Date)
                    .Select(p => new OHLCVBarDto(p.Date, p.Open, p.High, p.Low, p.Close, p.AdjClose, p.Volume))
                    .ToList();

                var analysis = await _python.RunFullTechnicalAnalysisAsync(
                    ticker, bars,
                    config.EnabledIndicators.ToList(),
                    config.EnabledPatterns.ToList());

                // Store detected patterns as signals
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
                    await _technicalRepo.AddAsync(signal);
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Technical analysis failed for {Ticker}", ticker);
            }
        }
    }

    public async Task IngestSentimentAsync(List<string> tickers, UserScanConfig config)
    {
        _logger.LogInformation("Ingesting sentiment for {Count} tickers", tickers.Count);
        var today = DateOnly.FromDateTime(DateTime.UtcNow);

        // Process in batches
        foreach (var batch in tickers.Chunk(10))
        {
            try
            {
                var response = await _python.RunSentimentPipelineAsync(
                    batch.ToList(), config.EnabledSentimentSources.ToList());

                foreach (var sentiment in response.Data.Where(d => d.Error is null))
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
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Sentiment analysis failed for batch");
            }
        }
    }
}
