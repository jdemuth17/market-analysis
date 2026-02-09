using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class StockRepository : Repository<Stock>, IStockRepository
{
    public StockRepository(MarketAnalysisDbContext db) : base(db) { }

    public async Task<Stock?> GetByTickerAsync(string ticker) =>
        await _dbSet.FirstOrDefaultAsync(s => s.Ticker == ticker.ToUpperInvariant());

    public async Task<List<Stock>> GetByTickersAsync(IEnumerable<string> tickers)
    {
        var upper = tickers.Select(t => t.ToUpperInvariant()).ToList();
        return await _dbSet.Where(s => upper.Contains(s.Ticker)).ToListAsync();
    }

    public async Task<Stock> GetOrCreateAsync(string ticker, string? name = null)
    {
        var upper = ticker.ToUpperInvariant();
        var stock = await _dbSet.FirstOrDefaultAsync(s => s.Ticker == upper);
        if (stock is not null) return stock;

        stock = new Stock
        {
            Ticker = upper,
            Name = name ?? upper,
            LastUpdatedUtc = DateTime.UtcNow,
        };
        await _dbSet.AddAsync(stock);
        await _db.SaveChangesAsync();
        return stock;
    }

    public async Task<List<Stock>> SearchAsync(string query, int maxResults = 20)
    {
        var lower = query.ToLowerInvariant();
        return await _dbSet
            .Where(s => s.Ticker.ToLower().Contains(lower) || s.Name.ToLower().Contains(lower))
            .OrderBy(s => s.Ticker)
            .Take(maxResults)
            .ToListAsync();
    }
}
