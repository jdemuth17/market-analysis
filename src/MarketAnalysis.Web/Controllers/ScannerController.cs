using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Interfaces;
using Microsoft.AspNetCore.Mvc;
using System.Text.Json;

namespace MarketAnalysis.Web.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ScannerController : ControllerBase
{
    private readonly IPythonServiceClient _python;
    private readonly ITechnicalSignalRepository _techRepo;
    private readonly IFundamentalRepository _fundRepo;
    private readonly ISentimentRepository _sentRepo;
    private readonly IStockRepository _stockRepo;
    private readonly IScanReportRepository _reportRepo;
    private readonly ILogger<ScannerController> _logger;

    public ScannerController(
        IPythonServiceClient python,
        ITechnicalSignalRepository techRepo,
        IFundamentalRepository fundRepo,
        ISentimentRepository sentRepo,
        IStockRepository stockRepo,
        IScanReportRepository reportRepo,
        ILogger<ScannerController> logger)
    {
        _python = python;
        _techRepo = techRepo;
        _fundRepo = fundRepo;
        _sentRepo = sentRepo;
        _stockRepo = stockRepo;
        _reportRepo = reportRepo;
        _logger = logger;
    }

    /// <summary>Get top movers from an index via the Python service.</summary>
    [HttpGet("top-movers")]
    public async Task<ActionResult<TopMoversResponseDto>> GetTopMovers(
        [FromQuery] string index = "sp500",
        [FromQuery] int topN = 25)
    {
        try
        {
            var http = HttpContext.RequestServices.GetRequiredService<IHttpClientFactory>()
                .CreateClient();
            http.BaseAddress = new Uri(
                HttpContext.RequestServices.GetRequiredService<IConfiguration>()["PythonService:BaseUrl"] ?? "http://localhost:8000");
            http.Timeout = TimeSpan.FromMinutes(10);

            var payload = new { index, top_n = topN };
            var opts = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
            var resp = await http.PostAsJsonAsync("/api/scanner/top-movers", payload, opts);
            resp.EnsureSuccessStatusCode();

            var json = await resp.Content.ReadFromJsonAsync<JsonElement>(opts);

            var gainers = Deserialize<List<TickerMoverDto>>(json, "top_gainers") ?? new();
            var losers = Deserialize<List<TickerMoverDto>>(json, "top_losers") ?? new();
            var active = Deserialize<List<TickerMoverDto>>(json, "most_active") ?? new();
            var scanned = json.TryGetProperty("total_scanned", out var ts) ? ts.GetInt32() : 0;
            var errors = json.TryGetProperty("errors", out var er) ? er.GetInt32() : 0;

            return Ok(new TopMoversResponseDto(gainers, losers, active, scanned, errors));
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error fetching top movers");
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>Get all recently detected patterns across all stocks in the database.</summary>
    [HttpGet("patterns")]
    public async Task<ActionResult<List<PatternScanResultDto>>> GetActivePatterns(
        [FromQuery] int days = 7)
    {
        try
        {
            var signals = await _techRepo.GetAllRecentAsync(days);

            var results = signals.Select(s => new PatternScanResultDto(
                s.Stock?.Ticker ?? $"Stock#{s.StockId}",
                s.Stock?.Name ?? "",
                s.Stock?.MarketCap,
                s.PatternType.ToString(),
                s.Direction.ToString(),
                s.Confidence,
                s.DetectedDate,
                s.Status ?? "Active"
            )).ToList();

            return Ok(results);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error fetching active patterns");
            return StatusCode(500, new { error = ex.Message });
        }
    }

    /// <summary>Get best prospect stocks by combining technical, fundamental, and sentiment scores.</summary>
    [HttpGet("best-prospects")]
    public async Task<ActionResult<List<BestProspectDto>>> GetBestProspects(
        [FromQuery] int limit = 50)
    {
        try
        {
            // Grab the latest reports across all categories and merge entries
            var reports = await _reportRepo.GetRecentAsync(8);
            var entryMap = new Dictionary<string, (double composite, double tech, double fund, double sent, int rank, string? pattern, string? direction)>();

            foreach (var report in reports)
            {
                var full = await _reportRepo.GetWithEntriesAsync(report.Id);
                if (full?.Entries is null) continue;

                foreach (var entry in full.Entries)
                {
                    var ticker = entry.Stock?.Ticker ?? "";
                    if (string.IsNullOrEmpty(ticker)) continue;

                    // Keep the best composite score seen for a ticker
                    if (!entryMap.ContainsKey(ticker) || entry.CompositeScore > entryMap[ticker].composite)
                    {
                        entryMap[ticker] = (
                            entry.CompositeScore,
                            entry.TechnicalScore,
                            entry.FundamentalScore,
                            entry.SentimentScore,
                            entry.Rank,
                            entry.PatternDetected,
                            entry.Direction
                        );
                    }
                }
            }

            var prospects = new List<BestProspectDto>();
            foreach (var kv in entryMap.OrderByDescending(x => x.Value.composite).Take(limit))
            {
                var stock = await _stockRepo.GetByTickerAsync(kv.Key);
                var fund = stock is not null ? await _fundRepo.GetLatestByStockAsync(stock.Id) : null;

                prospects.Add(new BestProspectDto(
                    kv.Key,
                    stock?.Name ?? "",
                    stock?.MarketCap,
                    stock?.Sector,
                    Math.Round(kv.Value.composite, 2),
                    Math.Round(kv.Value.tech, 2),
                    Math.Round(kv.Value.fund, 2),
                    Math.Round(kv.Value.sent, 2),
                    kv.Value.pattern,
                    kv.Value.direction,
                    fund?.RecommendationKey
                ));
            }

            return Ok(prospects);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error fetching best prospects");
            return StatusCode(500, new { error = ex.Message });
        }
    }

    private static T? Deserialize<T>(JsonElement root, string propertyName)
    {
        if (root.TryGetProperty(propertyName, out var prop))
        {
            var opts = new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
                PropertyNameCaseInsensitive = true,
            };
            return JsonSerializer.Deserialize<T>(prop.GetRawText(), opts);
        }
        return default;
    }
}
