using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class FundamentalRepository : Repository<FundamentalSnapshot>, IFundamentalRepository
{
    public FundamentalRepository(MarketAnalysisDbContext db) : base(db) { }

    public async Task<FundamentalSnapshot?> GetLatestByStockAsync(int stockId) =>
        await _dbSet
            .Where(f => f.StockId == stockId)
            .OrderByDescending(f => f.SnapshotDate)
            .FirstOrDefaultAsync();

    public async Task<List<FundamentalSnapshot>> GetByStockAsync(int stockId, int limit = 10) =>
        await _dbSet
            .Where(f => f.StockId == stockId)
            .OrderByDescending(f => f.SnapshotDate)
            .Take(limit)
            .ToListAsync();
}
