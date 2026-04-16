using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class WatchListRepository : Repository<WatchList>, IWatchListRepository
{
    public WatchListRepository(MarketAnalysisDbContext db) : base(db) { }

    public async Task<WatchList?> GetWithItemsAsync(int watchListId) =>
        await _dbSet
            .Include(w => w.Items)
                .ThenInclude(i => i.Stock)
            .FirstOrDefaultAsync(w => w.Id == watchListId);

    public async Task<List<WatchList>> GetAllWithItemCountAsync() =>
        await _dbSet
            .Include(w => w.Items)
            .ToListAsync();

    public async Task AddItemAsync(int watchListId, int stockId)
    {
        var exists = await _db.Set<WatchListItem>()
            .AnyAsync(i => i.WatchListId == watchListId && i.StockId == stockId);
        
        if (exists) return;

        await _db.Set<WatchListItem>().AddAsync(new WatchListItem
        {
            WatchListId = watchListId,
            StockId = stockId,
            AddedAtUtc = DateTime.UtcNow
        });
        await _db.SaveChangesAsync();
    }

    public async Task RemoveItemAsync(int watchListId, int stockId)
    {
        var item = await _db.Set<WatchListItem>()
            .FirstOrDefaultAsync(i => i.WatchListId == watchListId && i.StockId == stockId);
        
        if (item == null) return;

        _db.Set<WatchListItem>().Remove(item);
        await _db.SaveChangesAsync();
    }

    public async Task<bool> IsStockInWatchListAsync(int watchListId, int stockId) =>
        await _db.Set<WatchListItem>()
            .AnyAsync(i => i.WatchListId == watchListId && i.StockId == stockId);
}
