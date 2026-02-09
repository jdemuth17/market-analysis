using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Enums;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class ScanReportRepository : Repository<ScanReport>, IScanReportRepository
{
    public ScanReportRepository(MarketAnalysisDbContext db) : base(db) { }

    public async Task<List<ScanReport>> GetByDateAsync(DateOnly date) =>
        await _dbSet
            .Where(r => r.ReportDate == date)
            .OrderBy(r => r.Category)
            .ToListAsync();

    public async Task<ScanReport?> GetLatestByCategoryAsync(ReportCategory category) =>
        await _dbSet
            .Where(r => r.Category == category)
            .OrderByDescending(r => r.ReportDate)
            .FirstOrDefaultAsync();

    public async Task<List<ScanReport>> GetRecentAsync(int limit = 20) =>
        await _dbSet
            .OrderByDescending(r => r.ReportDate)
            .ThenBy(r => r.Category)
            .Take(limit)
            .ToListAsync();

    public async Task<ScanReport?> GetWithEntriesAsync(int reportId) =>
        await _dbSet
            .Include(r => r.Entries)
                .ThenInclude(e => e.Stock)
            .FirstOrDefaultAsync(r => r.Id == reportId);
}
