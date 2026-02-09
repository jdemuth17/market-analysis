using MarketAnalysis.Core.Enums;

namespace MarketAnalysis.Core.Entities;

public class ScanReport
{
    public int Id { get; set; }

    public DateOnly ReportDate { get; set; }
    public ReportCategory Category { get; set; }
    public DateTime GeneratedAtUtc { get; set; } = DateTime.UtcNow;

    /// <summary>JSON: copy of the configuration used to generate this report.</summary>
    public string ConfigSnapshot { get; set; } = "{}";

    public int TotalStocksScanned { get; set; }
    public int TotalMatches { get; set; }

    // Navigation
    public ICollection<ScanReportEntry> Entries { get; set; } = new List<ScanReportEntry>();
}
