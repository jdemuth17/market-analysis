using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
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

    /// <summary>
    /// Converts a PascalCase C# enum name to snake_case for Python.
    /// E.g. "DoubleTop" → "double_top", "RSI14" → "rsi_14", "SMA200" → "sma_200"
    /// </summary>
    private static string ToSnakeCase(string name)
    {
        // Insert underscore before uppercase letters preceded by lowercase or before digits preceded by letters
        var result = Regex.Replace(name, @"([a-z])([A-Z])", "$1_$2");
        result = Regex.Replace(result, @"([A-Z]+)([A-Z][a-z])", "$1_$2");
        result = Regex.Replace(result, @"([a-zA-Z])(\d)", "$1_$2");
        result = Regex.Replace(result, @"(\d)([a-zA-Z])", "$1_$2");
        return result.ToLowerInvariant();
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
            indicators = indicators.Select(i => ToSnakeCase(i.ToString())),
            patterns = patterns.Select(p => ToSnakeCase(p.ToString())),
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

    public async Task<BatchFundamentalScoreResponseDto> ScoreFundamentalsBatchAsync(List<FundamentalDataDto> items)
    {
        var payload = new BatchFundamentalScoreRequestDto(
            items.Select(fd => new FundamentalScoreRequestDto(
                Ticker: fd.Ticker,
                PeRatio: fd.PeRatio,
                ForwardPe: fd.ForwardPe,
                PegRatio: fd.PegRatio,
                DebtToEquity: fd.DebtToEquity,
                ProfitMargin: fd.ProfitMargin,
                ReturnOnEquity: fd.ReturnOnEquity,
                FreeCashFlow: fd.FreeCashFlow,
                RevenueGrowth: fd.RevenuePerShare,     // maps to revenue_growth in Python
                EarningsGrowth: fd.EarningsPerShare,    // maps to earnings_growth in Python
                CurrentPrice: fd.CurrentPrice,
                TargetMeanPrice: fd.TargetMeanPrice
            )).ToList()
        );
        var resp = await _http.PostAsJsonAsync("/api/fundamentals/score-batch", payload, JsonOpts);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<BatchFundamentalScoreResponseDto>(JsonOpts))!;
    }

    public async Task<List<string>> GetTickerListAsync(string indexName)
    {
        // Map display names to Python's expected lowercase keys
        var pythonKey = indexName switch
        {
            "S&P 500" or "SP500" or "s&p 500" => "sp500",
            "NASDAQ 100" or "NASDAQ100" or "nasdaq 100" => "nasdaq100",
            "NASDAQ" or "NASDAQ All" or "nasdaq" or "nasdaq_all" => "nasdaq_all",
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
