using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class IndexDefinitionRepository : Repository<IndexDefinition>, IIndexDefinitionRepository
{
    public IndexDefinitionRepository(MarketAnalysisDbContext db) : base(db) { }

    public async Task<List<IndexDefinition>> GetEnabledAsync() =>
        await _dbSet.Where(i => i.IsEnabled).ToListAsync();

    public async Task<IndexDefinition?> GetByNameAsync(string name) =>
        await _dbSet.FirstOrDefaultAsync(i => i.Name == name);
}
