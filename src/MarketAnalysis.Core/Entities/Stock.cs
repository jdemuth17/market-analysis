using System.ComponentModel.DataAnnotations;

namespace MarketAnalysis.Core.Entities;

public class Stock
{
    public int Id { get; set; }

    [Required, MaxLength(10)]
    public string Ticker { get; set; } = string.Empty;

    [MaxLength(200)]
    public string Name { get; set; } = string.Empty;

    [MaxLength(100)]
    public string? Sector { get; set; }

    [MaxLength(100)]
    public string? Industry { get; set; }

    [MaxLength(20)]
    public string? Exchange { get; set; }

    public decimal? MarketCap { get; set; }

    public bool IsActive { get; set; } = true;

    public DateTime LastUpdatedUtc { get; set; } = DateTime.UtcNow;

    // Navigation properties
    public ICollection<PriceHistory> PriceHistories { get; set; } = new List<PriceHistory>();
    public ICollection<TechnicalSignal> TechnicalSignals { get; set; } = new List<TechnicalSignal>();
    public ICollection<FundamentalSnapshot> FundamentalSnapshots { get; set; } = new List<FundamentalSnapshot>();
    public ICollection<SentimentScore> SentimentScores { get; set; } = new List<SentimentScore>();
    public ICollection<ScanReportEntry> ScanReportEntries { get; set; } = new List<ScanReportEntry>();
    public ICollection<WatchListItem> WatchListItems { get; set; } = new List<WatchListItem>();
}
