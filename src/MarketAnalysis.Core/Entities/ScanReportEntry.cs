namespace MarketAnalysis.Core.Entities;

public class ScanReportEntry
{
    public long Id { get; set; }

    public int ScanReportId { get; set; }
    public ScanReport ScanReport { get; set; } = null!;

    public int StockId { get; set; }
    public Stock Stock { get; set; } = null!;

    public double CompositeScore { get; set; }
    public double TechnicalScore { get; set; }
    public double FundamentalScore { get; set; }
    public double SentimentScore { get; set; }
    public int Rank { get; set; }

    public decimal? CurrentPrice { get; set; }
    public string? PatternDetected { get; set; }
    public string? Direction { get; set; }

    /// <summary>JSON: which criteria matched, detailed score breakdown.</summary>
    public string Reasoning { get; set; } = "{}";
}
