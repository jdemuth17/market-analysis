using System.ComponentModel.DataAnnotations;

namespace MarketAnalysis.Core.Entities;

public class WatchList
{
    public int Id { get; set; }

    [Required, MaxLength(100)]
    public string Name { get; set; } = string.Empty;

    [MaxLength(500)]
    public string? Description { get; set; }

    public DateTime CreatedAtUtc { get; set; } = DateTime.UtcNow;

    public ICollection<WatchListItem> Items { get; set; } = new List<WatchListItem>();
}

public class WatchListItem
{
    public int Id { get; set; }

    public int WatchListId { get; set; }
    public WatchList WatchList { get; set; } = null!;

    public int StockId { get; set; }
    public Stock Stock { get; set; } = null!;

    public DateTime AddedAtUtc { get; set; } = DateTime.UtcNow;
}
