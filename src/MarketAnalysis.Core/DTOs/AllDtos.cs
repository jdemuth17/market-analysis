using MarketAnalysis.Core.Enums;

namespace MarketAnalysis.Core.DTOs;

// --- Market Data DTOs ---

public record OHLCVBarDto(
    DateOnly Date, decimal Open, decimal High, decimal Low, decimal Close, decimal AdjClose, long Volume
);

public record FetchPricesRequestDto(
    List<string> Tickers, string Period = "6mo", string Interval = "1d"
);

public record TickerPriceDataDto(
    string Ticker, List<OHLCVBarDto> Bars, string? Error = null
);

public record FetchPricesResponseDto(
    List<TickerPriceDataDto> Data, int TotalTickers, int Successful, int Failed
);

// --- Fundamentals DTOs ---

public record FundamentalDataDto(
    string Ticker,
    string? CompanyName = null,
    string? Sector = null,
    string? Industry = null,
    string? Exchange = null,
    double? PeRatio = null,
    double? ForwardPe = null,
    double? PegRatio = null,
    double? PriceToBook = null,
    double? RevenuePerShare = null,
    double? EarningsPerShare = null,
    double? DebtToEquity = null,
    double? ProfitMargin = null,
    double? OperatingMargin = null,
    double? ReturnOnEquity = null,
    double? FreeCashFlow = null,
    double? DividendYield = null,
    double? Revenue = null,
    double? MarketCap = null,
    double? Beta = null,
    double? FiftyTwoWeekHigh = null,
    double? FiftyTwoWeekLow = null,
    double? CurrentPrice = null,
    double? TargetMeanPrice = null,
    string? RecommendationKey = null,
    string? Error = null
);

public record FetchFundamentalsResponseDto(
    List<FundamentalDataDto> Data, int TotalTickers, int Successful, int Failed
);

public record FundamentalScoreDto(
    string Ticker,
    double ValueScore,
    double QualityScore,
    double GrowthScore,
    double SafetyScore,
    double CompositeScore,
    Dictionary<string, double>? Details = null,
    string? Error = null
);

public record FundamentalScoreRequestDto(
    string Ticker,
    double? PeRatio = null,
    double? ForwardPe = null,
    double? PegRatio = null,
    double? DebtToEquity = null,
    double? ProfitMargin = null,
    double? ReturnOnEquity = null,
    double? FreeCashFlow = null,
    double? RevenueGrowth = null,
    double? EarningsGrowth = null,
    double? CurrentPrice = null,
    double? TargetMeanPrice = null
);

public record BatchFundamentalScoreRequestDto(
    List<FundamentalScoreRequestDto> Items
);

public record BatchFundamentalScoreResponseDto(
    List<FundamentalScoreDto> Scores
);

// --- Technical DTOs ---

public record IndicatorValueDto(
    string Name, Dictionary<string, double?> Values
);

public record DetectedPatternDto(
    string PatternType,
    string Direction,
    double Confidence,
    DateOnly StartDate,
    DateOnly EndDate,
    Dictionary<string, double> KeyLevels,
    string Status,
    Dictionary<string, object>? Metadata = null
);

public record TechnicalAnalysisResponseDto(
    string Ticker,
    List<IndicatorValueDto> Indicators,
    List<DetectedPatternDto> DetectedPatterns,
    string? Error = null
);

// --- Sentiment DTOs ---

public record SentimentResultDto(
    string Text, double Positive, double Negative, double Neutral, string Label
);

public record TickerSentimentDto(
    string Ticker,
    string Source,
    double PositiveScore,
    double NegativeScore,
    double NeutralScore,
    int SampleSize,
    List<SentimentResultDto> IndividualResults,
    List<string> Headlines,
    string? Error = null
);

public record FullSentimentResponseDto(
    List<TickerSentimentDto> Data, int TotalTickers, int TotalTextsAnalyzed
);

// --- Report DTOs ---

public record ScanReportDto(
    int Id,
    DateOnly ReportDate,
    ReportCategory Category,
    DateTime GeneratedAtUtc,
    int TotalStocksScanned,
    int TotalMatches,
    List<ScanReportEntryDto> Entries
);

public record ScanReportEntryDto(
    long Id,
    string Ticker,
    string StockName,
    decimal? CurrentPrice,
    double CompositeScore,
    double TechnicalScore,
    double FundamentalScore,
    double SentimentScore,
    int Rank,
    string? PatternDetected = null,
    string? Direction = null,
    Dictionary<string, object>? Reasoning = null
);

public record ScanReportSummaryDto(
    ReportCategory Category,
    int TotalMatches,
    List<ScanReportEntryDto> TopPicks,
    DateTime? LastScanUtc
);

public record DashboardDto(
    List<ScanReportSummaryDto> ReportSummaries,
    DateTime? LastScanUtc,
    DateTime? NextScheduledScan,
    int TotalStocksTracked
);

// --- Configuration DTOs ---

public record UserScanConfigDto(
    int Id,
    string Name,
    bool IsDefault,
    List<PatternType> EnabledPatterns,
    decimal? PriceRangeMin,
    decimal? PriceRangeMax,
    decimal? MinMarketCap,
    double? MaxPERatio,
    double? MaxDebtToEquity,
    double? MinProfitMargin,
    double? MinSentimentScore,
    int MinSentimentSampleSize,
    double TechnicalWeight,
    double FundamentalWeight,
    double SentimentWeight,
    List<ReportCategory> EnabledCategories,
    List<SentimentSource> EnabledSentimentSources,
    List<IndicatorType> EnabledIndicators
);

// --- WatchList DTOs ---

public record WatchListDto(
    int Id, string Name, string? Description, int ItemCount, DateTime CreatedAtUtc
);

public record WatchListDetailDto(
    int Id, string Name, string? Description, List<WatchListItemDto> Items
);

public record WatchListItemDto(
    int Id, string Ticker, string StockName, decimal? CurrentPrice, DateTime AddedAtUtc
);

// --- Stock Detail DTO ---

public record StockDetailDto(
    int Id,
    string Ticker,
    string Name,
    string? Sector,
    string? Industry,
    string? Exchange,
    decimal? MarketCap,
    decimal? CurrentPrice,
    List<OHLCVBarDto> RecentPrices,
    List<DetectedPatternDto> RecentPatterns,
    FundamentalDataDto? LatestFundamentals,
    List<TickerSentimentDto> RecentSentiment
);

// --- Scanner / Discovery DTOs ---

public record TickerMoverDto(
    string Ticker,
    string? Name,
    double? CurrentPrice,
    double? PreviousClose,
    double? Change,
    double? ChangePercent,
    long? Volume,
    long? AvgVolume,
    double? VolumeRatio,
    double? MarketCap,
    string? Sector,
    string? Error = null
);

public record TopMoversResponseDto(
    List<TickerMoverDto> TopGainers,
    List<TickerMoverDto> TopLosers,
    List<TickerMoverDto> MostActive,
    int TotalScanned,
    int Errors
);

public record PatternScanResultDto(
    string Ticker,
    string StockName,
    decimal? CurrentPrice,
    string PatternType,
    string Direction,
    double Confidence,
    DateOnly DetectedDate,
    string Status
);

public record BestProspectDto(
    string Ticker,
    string StockName,
    decimal? CurrentPrice,
    string? Sector,
    double CompositeScore,
    double TechnicalScore,
    double FundamentalScore,
    double SentimentScore,
    string? TopPattern,
    string? PatternDirection,
    string? Recommendation
);

public record ScannerResultsDto(
    TopMoversResponseDto? TopMovers,
    List<PatternScanResultDto> ActivePatterns,
    List<BestProspectDto> BestProspects,
    DateTime GeneratedAtUtc
);

// --- ML Service DTOs ---

public record MLFeatureImpactDto(
    string Feature,
    double Impact,
    double Value
);

public record MLStockPredictionDto(
    string Ticker,
    string Category,
    double XgboostScore,
    double? LstmScore,
    double EnsembleScore,
    double? PredictedReturnPct,
    double Confidence,
    List<MLFeatureImpactDto> TopFeatures
);

public record MLPredictResponseDto(
    List<MLStockPredictionDto> Predictions,
    int TotalTickers,
    List<string> CategoriesScored,
    string? ModelVersion
);
