namespace MarketAnalysis.Core.Entities;

public class FundamentalSnapshot
{
    public long Id { get; set; }

    public int StockId { get; set; }
    public Stock Stock { get; set; } = null!;

    public DateOnly SnapshotDate { get; set; }

    public double? PeRatio { get; set; }
    public double? ForwardPe { get; set; }
    public double? PegRatio { get; set; }
    public double? PriceToBook { get; set; }
    public double? RevenuePerShare { get; set; }
    public double? EarningsPerShare { get; set; }
    public double? DebtToEquity { get; set; }
    public double? ProfitMargin { get; set; }
    public double? OperatingMargin { get; set; }
    public double? ReturnOnEquity { get; set; }
    public decimal? FreeCashFlow { get; set; }
    public double? DividendYield { get; set; }
    public decimal? Revenue { get; set; }
    public decimal? MarketCap { get; set; }
    public double? Beta { get; set; }
    public decimal? FiftyTwoWeekHigh { get; set; }
    public decimal? FiftyTwoWeekLow { get; set; }
    public decimal? CurrentPrice { get; set; }
    public decimal? TargetMeanPrice { get; set; }
    public string? RecommendationKey { get; set; }

    // Scores from Python scoring engine
    public double ValueScore { get; set; }
    public double QualityScore { get; set; }
    public double GrowthScore { get; set; }
    public double SafetyScore { get; set; }
    public double CompositeScore { get; set; }

    /// <summary>JSON: Full raw data backup from yfinance info dict.</summary>
    public string RawData { get; set; } = "{}";
}
