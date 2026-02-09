using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Enums;
using MarketAnalysis.Core.Interfaces;
using Microsoft.Extensions.Logging;

namespace MarketAnalysis.Infrastructure.Services;

public class PythonServiceClient : IPythonServiceClient
{
    private readonly HttpClient _http;
    private readonly ILogger<PythonServiceClient> _logger;
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNameCaseInsensitive = true,
    };

    public PythonServiceClient(HttpClient http, ILogger<PythonServiceClient> logger)
    {
        _http = http;
        _logger = logger;
    }

    public async Task<FetchPricesResponseDto> FetchPricesAsync(
        List<string> tickers, string period = "6mo", string interval = "1d")
    {
        var payload = new { tickers, period, interval };
        var resp = await _http.PostAsJsonAsync("/api/market-data/fetch-prices", payload, JsonOpts);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<FetchPricesResponseDto>(JsonOpts))!;
    }

    public async Task<FetchFundamentalsResponseDto> FetchFundamentalsAsync(List<string> tickers)
    {
        var payload = new { tickers };
        var resp = await _http.PostAsJsonAsync("/api/market-data/fetch-fundamentals", payload, JsonOpts);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<FetchFundamentalsResponseDto>(JsonOpts))!;
    }

    public async Task<TechnicalAnalysisResponseDto> RunFullTechnicalAnalysisAsync(
        string ticker, List<OHLCVBarDto> bars,
        List<IndicatorType> indicators, List<PatternType> patterns, int lookbackDays = 120)
    {
        var payload = new
        {
            ticker,
            bars = bars.Select(b => new
            {
                date = b.Date.ToString("yyyy-MM-dd"),
                open = (double)b.Open,
                high = (double)b.High,
                low = (double)b.Low,
                close = (double)b.Close,
                adj_close = (double)b.AdjClose,
                volume = b.Volume,
            }),
            indicators = indicators.Select(i => i.ToString()),
            patterns = patterns.Select(p => p.ToString()),
            lookback_days = lookbackDays,
        };
        var resp = await _http.PostAsJsonAsync("/api/technicals/full-analysis", payload, JsonOpts);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<TechnicalAnalysisResponseDto>(JsonOpts))!;
    }

    public async Task<FullSentimentResponseDto> RunSentimentPipelineAsync(
        List<string> tickers, List<SentimentSource> sources, int maxItemsPerSource = 30)
    {
        var payload = new
        {
            tickers,
            sources = sources.Select(s => s.ToString().ToLowerInvariant()),
            max_items_per_source = maxItemsPerSource,
        };
        var resp = await _http.PostAsJsonAsync("/api/sentiment/full-pipeline", payload, JsonOpts);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<FullSentimentResponseDto>(JsonOpts))!;
    }

    public async Task<FundamentalScoreDto> ScoreFundamentalsAsync(FundamentalDataDto data)
    {
        var resp = await _http.PostAsJsonAsync("/api/fundamentals/score", data, JsonOpts);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<FundamentalScoreDto>(JsonOpts))!;
    }

    public async Task<List<string>> GetTickerListAsync(string indexName)
    {
        // Map display names to Python's expected lowercase keys
        var pythonKey = indexName switch
        {
            "S&P 500" or "SP500" or "s&p 500" => "sp500",
            "NASDAQ 100" or "NASDAQ100" or "nasdaq 100" => "nasdaq100",
            _ => indexName.ToLowerInvariant().Replace(" ", "").Replace("&", ""),
        };
        _logger.LogInformation("Fetching ticker list for {Index} (python key: {Key})", indexName, pythonKey);
        var resp = await _http.GetFromJsonAsync<JsonElement>(
            $"/api/market-data/ticker-lists/{Uri.EscapeDataString(pythonKey)}", JsonOpts);
        return resp.GetProperty("tickers").Deserialize<List<string>>(JsonOpts) ?? new();
    }

    public async Task<bool> HealthCheckAsync()
    {
        try
        {
            var resp = await _http.GetAsync("/api/health");
            return resp.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Python service health check failed");
            return false;
        }
    }
}
