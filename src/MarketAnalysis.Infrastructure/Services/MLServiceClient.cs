using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Enums;
using MarketAnalysis.Core.Interfaces;
using Microsoft.Extensions.Logging;

namespace MarketAnalysis.Infrastructure.Services;

public class MLServiceClient : IMLServiceClient
{
    private readonly HttpClient _http;
    private readonly ILogger<MLServiceClient> _logger;
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNameCaseInsensitive = true,
    };

    public MLServiceClient(HttpClient http, ILogger<MLServiceClient> logger)
    {
        _http = http;
        _logger = logger;
    }

    public async Task<MLPredictResponseDto> PredictAsync(
        List<string> tickers, List<ReportCategory> categories, bool includeShap = true)
    {
        var payload = new
        {
            tickers,
            categories = categories.Select(c => c.ToString()).ToList(),
            include_shap = includeShap,
        };

        _logger.LogInformation("ML predict: {Count} tickers, {Categories}", tickers.Count, string.Join(",", categories));

        var resp = await _http.PostAsJsonAsync("/api/ml/predict", payload, JsonOpts);
        resp.EnsureSuccessStatusCode();
        return (await resp.Content.ReadFromJsonAsync<MLPredictResponseDto>(JsonOpts))!;
    }

    public async Task<bool> HealthCheckAsync()
    {
        try
        {
            var resp = await _http.GetAsync("/api/ml/health");
            return resp.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "ML service health check failed");
            return false;
        }
    }
}
