using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace MarketAnalysis.Infrastructure.Repositories;

public class AiPredictionRepository : Repository<AiPrediction>, IAiPredictionRepository
{
    public AiPredictionRepository(MarketAnalysisDbContext db) : base(db) { }

    public async Task<List<AiPrediction>> GetByStockAsync(int stockId, int limit = 50)
    {
        return await _dbSet
            .Where(p => p.StockId == stockId)
            .OrderByDescending(p => p.PredictionDate)
            .Take(limit)
            .ToListAsync();
    }

    public async Task<List<AiPrediction>> GetRecentAsync(int days = 30)
    {
        var cutoff = DateOnly.FromDateTime(DateTime.UtcNow.AddDays(-days));
        return await _dbSet
            .Where(p => p.PredictionDate >= cutoff)
            .OrderByDescending(p => p.PredictionDate)
            .ToListAsync();
    }

    public async Task<List<AiPrediction>> GetUnevaluatedAsync(int horizonDays)
    {
        var targetDate = DateOnly.FromDateTime(DateTime.UtcNow.AddDays(-horizonDays));

        return horizonDays switch
        {
            5 => await _dbSet
                .Where(p => p.PredictionDate <= targetDate && p.OutcomeAt5Days == null)
                .ToListAsync(),
            10 => await _dbSet
                .Where(p => p.PredictionDate <= targetDate && p.OutcomeAt10Days == null)
                .ToListAsync(),
            30 => await _dbSet
                .Where(p => p.PredictionDate <= targetDate && p.OutcomeAt30Days == null)
                .ToListAsync(),
            _ => new List<AiPrediction>()
        };
    }

    public async Task<PredictionAccuracyDto> GetAccuracyStatsAsync()
    {
        var evaluated = await _dbSet
            .Where(p => p.EvaluatedAt != null)
            .ToListAsync();

        if (evaluated.Count == 0)
        {
            return new PredictionAccuracyDto(0, 0, 0, 0, 0, 0);
        }

        var total = evaluated.Count;
        var with5d = evaluated.Where(p => p.OutcomeAt5Days != null).ToList();
        var with10d = evaluated.Where(p => p.OutcomeAt10Days != null).ToList();
        var with30d = evaluated.Where(p => p.OutcomeAt30Days != null).ToList();

        var accuracy5d = with5d.Count > 0 ? with5d.Count(p => p.OutcomeAt5Days == "hit") / (double)with5d.Count : 0;
        var accuracy10d = with10d.Count > 0 ? with10d.Count(p => p.OutcomeAt10Days == "hit") / (double)with10d.Count : 0;
        var accuracy30d = with30d.Count > 0 ? with30d.Count(p => p.OutcomeAt30Days == "hit") / (double)with30d.Count : 0;
        var avgConf = evaluated.Average(p => p.Confidence);

        var highConf = evaluated.Where(p => p.Confidence >= 0.7).ToList();
        var highConfAccuracy = highConf.Count > 0
            ? highConf.Count(p => p.OutcomeAt30Days == "hit") / (double)highConf.Count
            : 0;

        return new PredictionAccuracyDto(
            total, accuracy5d, accuracy10d, accuracy30d, avgConf, highConfAccuracy
        );
    }
}
