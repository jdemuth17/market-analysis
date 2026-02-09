using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace MarketAnalysis.Web.Controllers;

[ApiController]
[Route("api/[controller]")]
public class DashboardController : ControllerBase
{
    private readonly IScanReportRepository _reportRepo;
    private readonly IStockRepository _stockRepo;

    public DashboardController(IScanReportRepository reportRepo, IStockRepository stockRepo)
    {
        _reportRepo = reportRepo;
        _stockRepo = stockRepo;
    }

    [HttpGet]
    public async Task<ActionResult<DashboardDto>> GetDashboard()
    {
        var allStocks = await _stockRepo.GetAllAsync();
        var recentReports = await _reportRepo.GetRecentAsync(20);

        var summaries = new List<ScanReportSummaryDto>();
        var categories = recentReports.Select(r => r.Category).Distinct();

        foreach (var cat in categories)
        {
            var latest = recentReports.Where(r => r.Category == cat).OrderByDescending(r => r.ReportDate).FirstOrDefault();
            if (latest is null) continue;

            var full = await _reportRepo.GetWithEntriesAsync(latest.Id);
            var topPicks = full?.Entries
                .OrderBy(e => e.Rank)
                .Take(5)
                .Select(e => new ScanReportEntryDto(
                    e.Id, e.Stock.Ticker, e.Stock.Name, e.CurrentPrice,
                    e.CompositeScore, e.TechnicalScore, e.FundamentalScore, e.SentimentScore,
                    e.Rank, e.PatternDetected, e.Direction, null))
                .ToList() ?? new();

            summaries.Add(new ScanReportSummaryDto(cat, latest.TotalMatches, topPicks, latest.GeneratedAtUtc));
        }

        return Ok(new DashboardDto(
            summaries,
            recentReports.FirstOrDefault()?.GeneratedAtUtc,
            null, // NextScheduledScan calculated by Hangfire
            allStocks.Count(s => s.IsActive)
        ));
    }
}
