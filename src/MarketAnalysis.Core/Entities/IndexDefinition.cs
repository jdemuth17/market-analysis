using System.ComponentModel.DataAnnotations;

namespace MarketAnalysis.Core.Entities;

public class IndexDefinition
{
    public int Id { get; set; }

    [Required, MaxLength(50)]
    public string Name { get; set; } = string.Empty;

    public bool IsEnabled { get; set; } = true;

    public string[] Tickers { get; set; } = Array.Empty<string>();

    public DateTime LastRefreshedUtc { get; set; } = DateTime.UtcNow;
}
