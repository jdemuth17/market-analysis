using MarketAnalysis.Core.Enums;
using System.ComponentModel.DataAnnotations;

namespace MarketAnalysis.Core.Entities;

public class UserScanConfig
{
    public int Id { get; set; }

    [Required, MaxLength(100)]
    public string Name { get; set; } = "Default";

    public bool IsDefault { get; set; }

    // Pattern filters
    public PatternType[] EnabledPatterns { get; set; } = new[]
    {
        PatternType.DoubleTop,
        PatternType.DoubleBottom,
        PatternType.HeadAndShoulders,
        PatternType.InverseHeadAndShoulders,
        PatternType.BullFlag,
        PatternType.BearFlag,
        PatternType.AscendingTriangle,
        PatternType.DescendingTriangle,
        PatternType.SymmetricalTriangle,
        PatternType.RisingWedge,
        PatternType.FallingWedge,
        PatternType.Pennant,
        PatternType.CupAndHandle,
    };

    // Price range
    public decimal? PriceRangeMin { get; set; }
    public decimal? PriceRangeMax { get; set; }

    // Volume filter (applied as pre-filter before expensive ingestion)
    public long? MinDailyVolume { get; set; }

    // Fundamental thresholds
    public decimal? MinMarketCap { get; set; }
    public double? MaxPERatio { get; set; }
    public double? MaxDebtToEquity { get; set; }
    public double? MinProfitMargin { get; set; }

    // Sentiment thresholds
    public double? MinSentimentScore { get; set; }
    public int MinSentimentSampleSize { get; set; } = 5;

    // Category weights (for composite score)
    public double TechnicalWeight { get; set; } = 0.40;
    public double FundamentalWeight { get; set; } = 0.35;
    public double SentimentWeight { get; set; } = 0.25;

    // Enabled features
    public ReportCategory[] EnabledCategories { get; set; } = new[]
    {
        ReportCategory.DayTrade,
        ReportCategory.SwingTrade,
        ReportCategory.ShortTermHold,
        ReportCategory.LongTermHold,
    };

    // News + Reddit provide sufficient sentiment coverage; StockTwits rate limiter (~3 req/min)
    // adds ~10 minutes of waiting for 30+ tickers with marginal data quality improvement
    public SentimentSource[] EnabledSentimentSources { get; set; } = new[]
    {
        SentimentSource.News,
        SentimentSource.Reddit,
    };

    public IndicatorType[] EnabledIndicators { get; set; } = new[]
    {
        IndicatorType.RSI14,
        IndicatorType.MACD,
        IndicatorType.SMA50,
        IndicatorType.SMA200,
        IndicatorType.BollingerBands,
        IndicatorType.ATR,
        IndicatorType.OBV,
    };

    /// <summary>
    /// When true, uses ML ensemble scoring (XGBoost + LSTM) instead of
    /// the legacy weighted-average scoring. Allows side-by-side comparison.
    /// </summary>
    public bool UseMlScoring { get; set; } = false;

    public DateTime CreatedAtUtc { get; set; } = DateTime.UtcNow;
    public DateTime UpdatedAtUtc { get; set; } = DateTime.UtcNow;
}
