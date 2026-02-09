using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class TechnicalSignalRepository : Repository<TechnicalSignal>, ITechnicalSignalRepository
{
    public TechnicalSignalRepository(MarketAnalysisDbContext db) : base(db) { }

    public async Task<List<TechnicalSignal>> GetByStockAsync(int stockId, int days = 30) =>
        await _dbSet
            .Where(t => t.StockId == stockId && t.DetectedDate >= DateOnly.FromDateTime(DateTime.UtcNow.AddDays(-days)))
            .OrderByDescending(t => t.DetectedDate)
            .ToListAsync();

    public async Task<List<TechnicalSignal>> GetByDateAsync(DateOnly date) =>
        await _dbSet
            .Where(t => t.DetectedDate == date)
            .Include(t => t.Stock)
            .ToListAsync();

    public async Task<List<TechnicalSignal>> GetRecentByStockAsync(int stockId, int limit = 10) =>
        await _dbSet
            .Where(t => t.StockId == stockId)
            .OrderByDescending(t => t.DetectedDate)
            .Take(limit)
            .ToListAsync();

    public async Task<List<TechnicalSignal>> GetAllRecentAsync(int days = 7) =>
        await _dbSet
            .Where(t => t.DetectedDate >= DateOnly.FromDateTime(DateTime.UtcNow.AddDays(-days)))
            .Include(t => t.Stock)
            .OrderByDescending(t => t.DetectedDate)
            .ThenByDescending(t => t.Confidence)
            .ToListAsync();
}
