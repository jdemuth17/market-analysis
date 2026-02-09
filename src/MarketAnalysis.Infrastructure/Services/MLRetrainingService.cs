using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using MarketAnalysis.Core.Interfaces;
using Microsoft.Extensions.Logging;

namespace MarketAnalysis.Infrastructure.Services;

public class MLRetrainingService : IMLRetrainingService
{
    private readonly HttpClient _http;
    private readonly ILogger<MLRetrainingService> _logger;
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNameCaseInsensitive = true,
    };

    public MLRetrainingService(HttpClient http, ILogger<MLRetrainingService> logger)
    {
        _http = http;
        _logger = logger;
    }

    public async Task RunRetrainingAsync(List<string> models, CancellationToken cancellationToken = default)
    {
        _logger.LogInformation("=== ML Retraining Started: {Models} ===", string.Join(", ", models));
        var sw = System.Diagnostics.Stopwatch.StartNew();

        // Step 1: Health check
        var healthResp = await _http.GetAsync("/api/ml/health", cancellationToken);
        if (!healthResp.IsSuccessStatusCode)
        {
            _logger.LogError("ML service is not available. Aborting retraining.");
            return;
        }

        // Step 2: Trigger backfill (refreshes training data)
        _logger.LogInformation("Step 1/3: Triggering data backfill...");
        var backfillPayload = new { phases = new[] { "prices", "technicals", "fundamentals", "labels" } };
        var backfillResp = await _http.PostAsJsonAsync("/api/ml/backfill", backfillPayload, JsonOpts, cancellationToken);
        backfillResp.EnsureSuccessStatusCode();

        var backfillResult = await backfillResp.Content.ReadFromJsonAsync<JobResponse>(JsonOpts, cancellationToken);
        var backfillJobId = backfillResult!.JobId;
        _logger.LogInformation("Backfill job started: {JobId}", backfillJobId);

        // Poll until backfill completes
        await PollJobAsync($"/api/ml/backfill/{backfillJobId}/status", "Backfill", cancellationToken);

        // Step 3: Trigger training
        cancellationToken.ThrowIfCancellationRequested();
        _logger.LogInformation("Step 2/3: Triggering model training for [{Models}]...", string.Join(", ", models));
        var trainPayload = new { models };
        var trainResp = await _http.PostAsJsonAsync("/api/ml/train", trainPayload, JsonOpts, cancellationToken);
        trainResp.EnsureSuccessStatusCode();

        var trainResult = await trainResp.Content.ReadFromJsonAsync<JobResponse>(JsonOpts, cancellationToken);
        var trainJobId = trainResult!.JobId;
        _logger.LogInformation("Training job started: {JobId}", trainJobId);

        // Poll until training completes
        await PollJobAsync($"/api/ml/train/{trainJobId}/status", "Training", cancellationToken);

        // Step 4: Log monitoring status
        _logger.LogInformation("Step 3/3: Checking model status...");
        try
        {
            var monitorResp = await _http.GetAsync("/api/ml/monitor", cancellationToken);
            if (monitorResp.IsSuccessStatusCode)
            {
                var monitorJson = await monitorResp.Content.ReadAsStringAsync(cancellationToken);
                _logger.LogInformation("Post-training monitoring: {Status}", monitorJson);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Could not fetch monitoring status after training");
        }

        sw.Stop();
        _logger.LogInformation("=== ML Retraining Complete in {Elapsed:F1}s ===", sw.Elapsed.TotalSeconds);
    }

    private async Task PollJobAsync(string statusUrl, string jobName, CancellationToken cancellationToken)
    {
        const int maxPollMinutes = 120;
        var deadline = DateTime.UtcNow.AddMinutes(maxPollMinutes);

        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await Task.Delay(TimeSpan.FromSeconds(15), cancellationToken);

            try
            {
                var resp = await _http.GetAsync(statusUrl, cancellationToken);
                if (!resp.IsSuccessStatusCode) continue;

                var status = await resp.Content.ReadFromJsonAsync<JobStatusResponse>(JsonOpts, cancellationToken);
                if (status is null) continue;

                _logger.LogInformation("{Job} status: {Status}", jobName, status.Status);

                if (status.Status == "completed")
                    return;

                if (status.Status == "failed")
                    throw new InvalidOperationException($"{jobName} failed: {status.Error}");
            }
            catch (HttpRequestException ex)
            {
                _logger.LogWarning(ex, "Error polling {Job} status, will retry", jobName);
            }
        }

        throw new TimeoutException($"{jobName} did not complete within {maxPollMinutes} minutes");
    }

    private record JobResponse(string Status, string JobId, string Message);
    private record JobStatusResponse(string JobId, string Status, string? Error = null);
}
