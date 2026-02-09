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
            .Select(w => new WatchList
            {
                Id = w.Id,
                Name = w.Name,
                Description = w.Description,
                CreatedAtUtc = w.CreatedAtUtc,
                Items = w.Items, // EF Core will handle the count
            })
            .ToListAsync();
}
