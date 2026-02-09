namespace MarketAnalysis.Core.Entities;

public class PriceHistory
{
    public long Id { get; set; }

    public int StockId { get; set; }
    public Stock Stock { get; set; } = null!;

    public DateOnly Date { get; set; }

    public decimal Open { get; set; }
    public decimal High { get; set; }
    public decimal Low { get; set; }
    public decimal Close { get; set; }
    public decimal AdjClose { get; set; }
    public long Volume { get; set; }
}
