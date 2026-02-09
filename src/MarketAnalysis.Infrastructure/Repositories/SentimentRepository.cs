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
}
