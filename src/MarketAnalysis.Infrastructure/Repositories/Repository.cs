using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class Repository<T> : IRepository<T> where T : class
{
    protected readonly MarketAnalysisDbContext _db;
    protected readonly DbSet<T> _dbSet;

    public Repository(MarketAnalysisDbContext db)
    {
        _db = db;
        _dbSet = db.Set<T>();
    }

    public virtual async Task<T?> GetByIdAsync(int id) => await _dbSet.FindAsync(id);

    public virtual async Task<List<T>> GetAllAsync() => await _dbSet.ToListAsync();

    public virtual async Task<T> AddAsync(T entity)
    {
        await _dbSet.AddAsync(entity);
        await _db.SaveChangesAsync();
        return entity;
    }

    public virtual async Task AddRangeAsync(IEnumerable<T> entities)
    {
        await _dbSet.AddRangeAsync(entities);
        await _db.SaveChangesAsync();
    }

    public virtual async Task UpdateAsync(T entity)
    {
        _dbSet.Update(entity);
        await _db.SaveChangesAsync();
    }

    public virtual async Task DeleteAsync(T entity)
    {
        _dbSet.Remove(entity);
        await _db.SaveChangesAsync();
    }

    public virtual async Task SaveChangesAsync() => await _db.SaveChangesAsync();
}
