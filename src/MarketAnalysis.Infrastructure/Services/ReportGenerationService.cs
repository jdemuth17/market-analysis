using System.Text.Json;
using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Enums;
using MarketAnalysis.Core.Interfaces;
using Microsoft.Extensions.Logging;

namespace MarketAnalysis.Infrastructure.Services;

public class ReportGenerationService : IReportGenerationService
{
    private readonly IStockRepository _stockRepo;
    private readonly IPriceHistoryRepository _priceRepo;
    private readonly ITechnicalSignalRepository _technicalRepo;
    private readonly IFundamentalRepository _fundamentalRepo;
    private readonly ISentimentRepository _sentimentRepo;
    private readonly IScanReportRepository _reportRepo;
    private readonly IMLServiceClient? _mlClient;
    private readonly ILogger<ReportGenerationService> _logger;

    public ReportGenerationService(
        IStockRepository stockRepo,
        IPriceHistoryRepository priceRepo,
        ITechnicalSignalRepository technicalRepo,
        IFundamentalRepository fundamentalRepo,
        ISentimentRepository sentimentRepo,
        IScanReportRepository reportRepo,
        ILogger<ReportGenerationService> logger,
        IMLServiceClient? mlClient = null)
    {
        _stockRepo = stockRepo;
        _priceRepo = priceRepo;
        _technicalRepo = technicalRepo;
        _fundamentalRepo = fundamentalRepo;
        _sentimentRepo = sentimentRepo;
        _reportRepo = reportRepo;
        _logger = logger;
        _mlClient = mlClient;
    }

    public async Task<List<ScanReport>> GenerateReportsAsync(UserScanConfig config, DateOnly reportDate)
    {
        _logger.LogInformation("Generating reports for {Date}", reportDate);
        var reports = new List<ScanReport>();
        var allStocks = await _stockRepo.GetAllAsync();
        var activeStocks = allStocks.Where(s => s.IsActive).ToList();
        var activeStockIds = activeStocks.Select(s => s.Id).ToList();

        _logger.LogInformation("Bulk-loading data for {Count} active stocks", activeStocks.Count);

        // Bulk load all data in 4 queries instead of N*4 queries
        var allLatestPrices = await _priceRepo.GetLatestForStocksAsync(activeStockIds);
        var allFundamentals = await _fundamentalRepo.GetLatestForStocksAsync(activeStockIds);
        var allSignals = await _technicalRepo.GetRecentForStocksAsync(activeStockIds, 30);
        var allSentiment = await _sentimentRepo.GetLatestForStocksAsync(activeStockIds);

        _logger.LogInformation("Bulk load complete: {Prices} prices, {Fund} fundamentals, {Sig} signal groups, {Sent} sentiment groups",
            allLatestPrices.Count, allFundamentals.Count, allSignals.Count, allSentiment.Count);

        // Pre-filter by price range
        var filteredStocks = new List<(Stock stock, PriceHistory? latestPrice, FundamentalSnapshot? fundamental,
            List<TechnicalSignal> signals, List<SentimentScore> sentiment)>();

        foreach (var stock in activeStocks)
        {
            if (!allLatestPrices.TryGetValue(stock.Id, out var latestPrice)) continue;

            // Price range filter
            if (config.PriceRangeMin.HasValue && latestPrice.Close < config.PriceRangeMin.Value) continue;
            if (config.PriceRangeMax.HasValue && latestPrice.Close > config.PriceRangeMax.Value) continue;

            allFundamentals.TryGetValue(stock.Id, out var fundamental);
            allSignals.TryGetValue(stock.Id, out var signals);
            allSentiment.TryGetValue(stock.Id, out var sentiment);

            // Fundamental filters
            if (config.MaxPERatio.HasValue && fundamental?.PeRatio > config.MaxPERatio.Value) continue;
            if (config.MaxDebtToEquity.HasValue && fundamental?.DebtToEquity > config.MaxDebtToEquity.Value) continue;
            if (config.MinProfitMargin.HasValue && fundamental?.ProfitMargin < config.MinProfitMargin.Value) continue;
            if (config.MinMarketCap.HasValue && fundamental?.MarketCap < config.MinMarketCap.Value) continue;

            filteredStocks.Add((stock, latestPrice, fundamental, signals ?? new List<TechnicalSignal>(), sentiment ?? new List<SentimentScore>()));
        }

        _logger.LogInformation("Filtered {Count}/{Total} stocks meet criteria",
            filteredStocks.Count, activeStocks.Count);

        // ML scoring path: use ensemble predictions if enabled and ML service available
        Dictionary<(string ticker, ReportCategory category), MLStockPredictionDto>? mlPredictions = null;
        if (config.UseMlScoring && _mlClient != null)
        {
            try
            {
                var mlHealthy = await _mlClient.HealthCheckAsync();
                if (mlHealthy)
                {
                    var tickers = filteredStocks.Select(f => f.stock.Ticker).ToList();
                    var mlResponse = await _mlClient.PredictAsync(
                        tickers, config.EnabledCategories.ToList());

                    mlPredictions = mlResponse.Predictions.ToDictionary(
                        p => (p.Ticker, Enum.Parse<ReportCategory>(p.Category)),
                        p => p);

                    _logger.LogInformation("ML scoring: received {Count} predictions", mlResponse.Predictions.Count);
                }
                else
                {
                    _logger.LogWarning("ML service unhealthy, falling back to legacy scoring");
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "ML scoring failed, falling back to legacy scoring");
            }
        }

        var configJson = JsonSerializer.Serialize(config);

        foreach (var category in config.EnabledCategories)
        {
            var report = new ScanReport
            {
                ReportDate = reportDate,
                Category = category,
                GeneratedAtUtc = DateTime.UtcNow,
                ConfigSnapshot = configJson,
                TotalStocksScanned = activeStocks.Count,
            };

            var entries = new List<ScanReportEntry>();

            foreach (var (stock, latestPrice, fundamental, signals, sentiment) in filteredStocks)
            {
                // Check for ML prediction first
                if (mlPredictions != null &&
                    mlPredictions.TryGetValue((stock.Ticker, category), out var mlPred))
                {
                    if (mlPred.EnsembleScore < 30) continue; // Minimum threshold

                    var mlReasoning = new Dictionary<string, object>
                    {
                        ["scoringMethod"] = "ml_ensemble",
                        ["xgboostScore"] = mlPred.XgboostScore,
                        ["lstmScore"] = mlPred.LstmScore ?? 0,
                        ["ensembleScore"] = mlPred.EnsembleScore,
                        ["modelConfidence"] = mlPred.Confidence,
                        ["topDrivers"] = mlPred.TopFeatures.Select(f =>
                            $"{f.Feature} (value={f.Value:F2}) contributed {f.Impact:+0.0;-0.0} points").ToList(),
                    };

                    entries.Add(new ScanReportEntry
                    {
                        StockId = stock.Id,
                        CompositeScore = mlPred.EnsembleScore,
                        TechnicalScore = mlPred.XgboostScore, // XGBoost as technical proxy
                        FundamentalScore = mlPred.LstmScore ?? mlPred.XgboostScore,
                        SentimentScore = mlPred.Confidence * 100,
                        PatternDetected = mlPred.TopFeatures.FirstOrDefault()?.Feature,
                        Direction = mlPred.Confidence >= 0.5 ? "Bullish" : "Bearish",
                        CurrentPrice = latestPrice!.Close,
                        Reasoning = JsonSerializer.Serialize(mlReasoning),
                    });
                    continue;
                }

                // Legacy scoring path
                var scores = ScoreForCategory(category, stock, latestPrice!, fundamental, signals, sentiment, config);
                if (scores.composite < 30) continue; // Minimum threshold

                var reasoning = new Dictionary<string, object>
                {
                    ["scoringMethod"] = "legacy_weighted",
                    ["technicalScore"] = scores.technical,
                    ["fundamentalScore"] = scores.fundamental,
                    ["sentimentScore"] = scores.sentiment,
                    ["topPattern"] = scores.topPattern ?? "None",
                    ["direction"] = scores.direction ?? "None",
                    ["details"] = scores.details,
                };

                entries.Add(new ScanReportEntry
                {
                    StockId = stock.Id,
                    CompositeScore = scores.composite,
                    TechnicalScore = scores.technical,
                    FundamentalScore = scores.fundamental,
                    SentimentScore = scores.sentiment,
                    PatternDetected = scores.topPattern,
                    Direction = scores.direction,
                    CurrentPrice = latestPrice!.Close,
                    Reasoning = JsonSerializer.Serialize(reasoning),
                });
            }

            // Rank entries
            var ranked = entries.OrderByDescending(e => e.CompositeScore).ToList();
            for (int i = 0; i < ranked.Count; i++)
                ranked[i].Rank = i + 1;

            report.TotalMatches = ranked.Count;
            report.Entries = ranked.Take(50).ToList(); // Top 50 per category
            await _reportRepo.AddAsync(report);
            reports.Add(report);

            _logger.LogInformation("Report {Category}: {Matches} matches ({Method})",
                category, ranked.Count,
                mlPredictions != null ? "ML" : "legacy");
        }

        return reports;
    }

    private (double composite, double technical, double fundamental, double sentiment,
        string? topPattern, string? direction, Dictionary<string, string> details)
        ScoreForCategory(
            ReportCategory category, Stock stock, PriceHistory latestPrice,
            FundamentalSnapshot? fundamental, List<TechnicalSignal> signals,
            List<SentimentScore> sentiment, UserScanConfig config)
    {
        double techScore = ScoreTechnical(category, latestPrice, signals);
        double fundScore = ScoreFundamental(category, fundamental);
        double sentScore = ScoreSentiment(sentiment, config.MinSentimentSampleSize);

        double composite = (techScore * config.TechnicalWeight)
                         + (fundScore * config.FundamentalWeight)
                         + (sentScore * config.SentimentWeight);

        var topSignal = signals.OrderByDescending(s => s.Confidence).FirstOrDefault();
        var details = new Dictionary<string, string>();

        switch (category)
        {
            case ReportCategory.DayTrade:
                details["focus"] = "Volume + Volatility + Pattern + Sentiment";
                break;
            case ReportCategory.SwingTrade:
                details["focus"] = "Pattern near breakout + RSI + MACD alignment";
                break;
            case ReportCategory.ShortTermHold:
                details["focus"] = "Confirmed pattern + Fundamentals + Positive sentiment";
                break;
            case ReportCategory.LongTermHold:
                details["focus"] = "Undervalued + FCF + Low debt + Revenue growth";
                break;
        }

        return (
            Math.Round(composite, 2),
            Math.Round(techScore, 2),
            Math.Round(fundScore, 2),
            Math.Round(sentScore, 2),
            topSignal?.PatternType.ToString(),
            topSignal?.Direction.ToString(),
            details
        );
    }

    private double ScoreTechnical(ReportCategory category, PriceHistory latestPrice, List<TechnicalSignal> signals)
    {
        double score = 0;
        if (!signals.Any()) return 20; // Base score for no signals

        // Pattern quality
        var recentSignals = signals.Where(s => s.DetectedDate >= DateOnly.FromDateTime(DateTime.UtcNow.AddDays(-7))).ToList();
        var bestConfidence = recentSignals.Any() ? recentSignals.Max(s => s.Confidence) : 0;

        score += bestConfidence * 40; // Pattern confidence contributes up to 40

        // Bullish bias
        var bullishCount = recentSignals.Count(s => s.Direction == SignalDirection.Bullish);
        var bearishCount = recentSignals.Count(s => s.Direction == SignalDirection.Bearish);
        if (bullishCount > bearishCount) score += 20;
        else if (bullishCount == bearishCount && bullishCount > 0) score += 10;

        switch (category)
        {
            case ReportCategory.DayTrade:
                // Favor high-confidence, near-breakout patterns
                if (bestConfidence > 0.7) score += 20;
                score += Math.Min(recentSignals.Count * 5, 20); // More signals = more volatile = better for day trade
                break;

            case ReportCategory.SwingTrade:
                // Favor patterns in progress
                var activePatterns = recentSignals.Where(s => s.Status == "forming" || s.Status == "active").ToList();
                score += activePatterns.Count * 10;
                break;

            case ReportCategory.ShortTermHold:
                // Favor confirmed patterns
                var confirmedPatterns = recentSignals.Where(s => s.Status == "confirmed" || s.Status == "completed").ToList();
                score += confirmedPatterns.Count * 15;
                break;

            case ReportCategory.LongTermHold:
                // Technical is less important for long holds, but trend matters
                if (bullishCount >= 2) score += 20;
                break;
        }

        return Math.Min(score, 100);
    }

    private double ScoreFundamental(ReportCategory category, FundamentalSnapshot? fundamental)
    {
        if (fundamental is null) return 30; // Neutral if no data

        double score = fundamental.CompositeScore; // Already 0-100 from Python

        switch (category)
        {
            case ReportCategory.DayTrade:
                // Day trades don't care much about fundamentals
                return 50; // Neutral

            case ReportCategory.SwingTrade:
                // Moderate importance
                return score * 0.7 + 30; // Compressed range 30-100

            case ReportCategory.ShortTermHold:
                // Important
                return score;

            case ReportCategory.LongTermHold:
                // Very important - boost for value + safety
                double longScore = 0;
                longScore += fundamental.ValueScore * 0.3;
                longScore += fundamental.QualityScore * 0.25;
                longScore += fundamental.GrowthScore * 0.2;
                longScore += fundamental.SafetyScore * 0.25;
                return longScore;
        }

        return score;
    }

    private double ScoreSentiment(List<SentimentScore> sentiment, int minSampleSize)
    {
        if (!sentiment.Any()) return 50; // Neutral if no data

        var totalSamples = sentiment.Sum(s => s.SampleSize);
        if (totalSamples < minSampleSize) return 50;

        // Weighted average across sources
        double weightedPositive = 0, weightedNegative = 0, totalWeight = 0;

        foreach (var s in sentiment)
        {
            double weight = s.Source switch
            {
                SentimentSource.News => 1.5,     // News is more reliable
                SentimentSource.Reddit => 0.8,    // Reddit is noisy
                SentimentSource.StockTwits => 1.0,
                _ => 1.0,
            };

            weightedPositive += s.PositiveScore * weight * s.SampleSize;
            weightedNegative += s.NegativeScore * weight * s.SampleSize;
            totalWeight += weight * s.SampleSize;
        }

        if (totalWeight == 0) return 50;

        double avgPositive = weightedPositive / totalWeight;
        double avgNegative = weightedNegative / totalWeight;

        // Convert to 0-100 score (positive - negative, normalized)
        double netSentiment = avgPositive - avgNegative; // Range: -1 to 1
        double score = (netSentiment + 1) * 50; // Map to 0-100

        return Math.Clamp(score, 0, 100);
    }
}
