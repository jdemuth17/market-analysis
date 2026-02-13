using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class SentimentRepository : Repository<SentimentScore>, ISentimentRepository
{
    public SentimentRepository(MarketAnalysisDbContext db) : base(db) { }

    public async Task<List<SentimentScore>> GetByStockAsync(int stockId, int days = 30) =>
        await _dbSet
            .Where(s => s.StockId == stockId && s.AnalysisDate >= DateOnly.FromDateTime(DateTime.UtcNow.AddDays(-days)))
            .OrderByDescending(s => s.AnalysisDate)
            .ToListAsync();

    public async Task<List<SentimentScore>> GetByStockAndDateAsync(int stockId, DateOnly date) =>
        await _dbSet
            .Where(s => s.StockId == stockId && s.AnalysisDate == date)
            .ToListAsync();

    public async Task<List<SentimentScore>> GetLatestByStockAsync(int stockId) =>
        await _dbSet
            .Where(s => s.StockId == stockId)
            .GroupBy(s => s.Source)
            .Select(g => g.OrderByDescending(s => s.AnalysisDate).First())
            .ToListAsync();

    public async Task<Dictionary<int, List<SentimentScore>>> GetLatestForStocksAsync(IEnumerable<int> stockIds)
    {
        var idList = stockIds.ToList();
        // Get the latest sentiment per stock per source
        var scores = await _dbSet
            .Where(s => idList.Contains(s.StockId))
            .GroupBy(s => new { s.StockId, s.Source })
            .Select(g => g.OrderByDescending(s => s.AnalysisDate).First())
            .ToListAsync();

        return scores.GroupBy(s => s.StockId)
            .ToDictionary(g => g.Key, g => g.ToList());
    }
}
