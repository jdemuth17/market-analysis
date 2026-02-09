using MarketAnalysis.Core.Enums;

namespace MarketAnalysis.Core.Entities;

public class SentimentScore
{
    public long Id { get; set; }

    public int StockId { get; set; }
    public Stock Stock { get; set; } = null!;

    public DateOnly AnalysisDate { get; set; }

    public SentimentSource Source { get; set; }

    public double PositiveScore { get; set; }
    public double NegativeScore { get; set; }
    public double NeutralScore { get; set; }
    public int SampleSize { get; set; }

    /// <summary>JSON: raw text samples collected.</summary>
    public string Headlines { get; set; } = "[]";
}
