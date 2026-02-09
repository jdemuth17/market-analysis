using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class PriceHistoryRepository : Repository<PriceHistory>, IPriceHistoryRepository
{
    public PriceHistoryRepository(MarketAnalysisDbContext db) : base(db) { }

    public async Task<List<PriceHistory>> GetByStockAsync(int stockId, int days = 365) =>
        await _dbSet
            .Where(p => p.StockId == stockId && p.Date >= DateOnly.FromDateTime(DateTime.UtcNow.AddDays(-days)))
            .OrderByDescending(p => p.Date)
            .ToListAsync();

    public async Task<List<PriceHistory>> GetByStockAndDateRangeAsync(int stockId, DateOnly from, DateOnly to) =>
        await _dbSet
            .Where(p => p.StockId == stockId && p.Date >= from && p.Date <= to)
            .OrderBy(p => p.Date)
            .ToListAsync();

    public async Task<PriceHistory?> GetLatestAsync(int stockId) =>
        await _dbSet
            .Where(p => p.StockId == stockId)
            .OrderByDescending(p => p.Date)
            .FirstOrDefaultAsync();

    public async Task UpsertRangeAsync(int stockId, IEnumerable<PriceHistory> prices)
    {
        var existingDates = await _dbSet
            .Where(p => p.StockId == stockId)
            .Select(p => p.Date)
            .ToHashSetAsync();

        var newPrices = prices.Where(p => !existingDates.Contains(p.Date)).ToList();

        if (newPrices.Count > 0)
        {
            foreach (var p in newPrices) p.StockId = stockId;
            await _dbSet.AddRangeAsync(newPrices);
            await _db.SaveChangesAsync();
        }
    }
}

internal static class QueryableExtensions
{
    public static async Task<HashSet<T>> ToHashSetAsync<T>(this IQueryable<T> source)
    {
        var list = await source.ToListAsync();
        return new HashSet<T>(list);
    }
}
