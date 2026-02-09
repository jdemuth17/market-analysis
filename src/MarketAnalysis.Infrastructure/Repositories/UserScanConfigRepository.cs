using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class UserScanConfigRepository : Repository<UserScanConfig>, IUserScanConfigRepository
{
    public UserScanConfigRepository(MarketAnalysisDbContext db) : base(db) { }

    public async Task<UserScanConfig?> GetDefaultAsync() =>
        await _dbSet.FirstOrDefaultAsync(c => c.IsDefault);

    public async Task SetDefaultAsync(int configId)
    {
        // Remove default from all
        var allConfigs = await _dbSet.ToListAsync();
        foreach (var c in allConfigs)
            c.IsDefault = c.Id == configId;

        await _db.SaveChangesAsync();
    }
}
