using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Enums;
using MarketAnalysis.Core.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace MarketAnalysis.Web.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ReportsController : ControllerBase
{
    private readonly IScanReportRepository _reportRepo;

    public ReportsController(IScanReportRepository reportRepo)
    {
        _reportRepo = reportRepo;
    }

    [HttpGet]
    public async Task<ActionResult<List<ScanReportDto>>> GetRecent([FromQuery] int limit = 20)
    {
        var reports = await _reportRepo.GetRecentAsync(limit);
        return Ok(reports.Select(r => new ScanReportDto(
            r.Id, r.ReportDate, r.Category, r.GeneratedAtUtc,
            r.TotalStocksScanned, r.TotalMatches, new())).ToList());
    }

    [HttpGet("{id:int}")]
    public async Task<ActionResult<ScanReportDto>> GetById(int id)
    {
        var report = await _reportRepo.GetWithEntriesAsync(id);
        if (report is null) return NotFound();

        var entries = report.Entries.OrderBy(e => e.Rank).Select(e => new ScanReportEntryDto(
            e.Id, e.Stock.Ticker, e.Stock.Name, e.CurrentPrice,
            e.CompositeScore, e.TechnicalScore, e.FundamentalScore, e.SentimentScore,
            e.Rank, e.PatternDetected, e.Direction, null)).ToList();

        return Ok(new ScanReportDto(
            report.Id, report.ReportDate, report.Category, report.GeneratedAtUtc,
            report.TotalStocksScanned, report.TotalMatches, entries));
    }

    [HttpGet("by-date/{date}")]
    public async Task<ActionResult<List<ScanReportDto>>> GetByDate(DateOnly date)
    {
        var reports = await _reportRepo.GetByDateAsync(date);
        return Ok(reports.Select(r => new ScanReportDto(
            r.Id, r.ReportDate, r.Category, r.GeneratedAtUtc,
            r.TotalStocksScanned, r.TotalMatches, new())).ToList());
    }

    [HttpGet("latest/{category}")]
    public async Task<ActionResult<ScanReportDto>> GetLatestByCategory(ReportCategory category)
    {
        var report = await _reportRepo.GetLatestByCategoryAsync(category);
        if (report is null) return NotFound();

        var full = await _reportRepo.GetWithEntriesAsync(report.Id);
        var entries = full!.Entries.OrderBy(e => e.Rank).Select(e => new ScanReportEntryDto(
            e.Id, e.Stock.Ticker, e.Stock.Name, e.CurrentPrice,
            e.CompositeScore, e.TechnicalScore, e.FundamentalScore, e.SentimentScore,
            e.Rank, e.PatternDetected, e.Direction, null)).ToList();

        return Ok(new ScanReportDto(
            full.Id, full.ReportDate, full.Category, full.GeneratedAtUtc,
            full.TotalStocksScanned, full.TotalMatches, entries));
    }
}
