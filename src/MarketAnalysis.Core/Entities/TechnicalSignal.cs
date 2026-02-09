using MarketAnalysis.Core.Enums;

namespace MarketAnalysis.Core.Entities;

public class TechnicalSignal
{
    public long Id { get; set; }

    public int StockId { get; set; }
    public Stock Stock { get; set; } = null!;

    public DateOnly DetectedDate { get; set; }

    public PatternType PatternType { get; set; }
    public SignalDirection Direction { get; set; }

    public double Confidence { get; set; }

    public DateOnly StartDate { get; set; }
    public DateOnly EndDate { get; set; }

    public string Status { get; set; } = "detected";

    /// <summary>JSON: resistance, support, neckline, target, etc.</summary>
    public string KeyPriceLevels { get; set; } = "{}";

    /// <summary>JSON: additional pattern-specific metadata.</summary>
    public string? Metadata { get; set; }
}
