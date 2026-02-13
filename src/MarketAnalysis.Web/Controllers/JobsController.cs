using MarketAnalysis.Core.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace MarketAnalysis.Web.Controllers;

[ApiController]
[Route("api/[controller]")]
public class JobsController : ControllerBase
{
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IPythonServiceClient _python;

    public JobsController(IServiceScopeFactory scopeFactory, IPythonServiceClient python)
    {
        _scopeFactory = scopeFactory;
        _python = python;
    }

    /// <summary>Trigger a full scan manually.</summary>
    [HttpPost("trigger-scan")]
    public ActionResult TriggerScan()
    {
        // Run in background with its own DI scope so DbContext is not disposed
        _ = Task.Run(async () =>
        {
            using var scope = _scopeFactory.CreateScope();
            var scanService = scope.ServiceProvider.GetRequiredService<IDailyScanService>();
            try { await scanService.RunFullScanAsync(); }
            catch { /* logged internally */ }
        });

        return Accepted(new { message = "Scan triggered. Check logs for progress." });
    }

    /// <summary>Get Python service health status.</summary>
    [HttpGet("health")]
    public async Task<ActionResult> HealthCheck()
    {
        var pythonHealthy = await _python.HealthCheckAsync();
        return Ok(new
        {
            status = "ok",
            pythonService = pythonHealthy ? "healthy" : "unavailable",
            timestamp = DateTime.UtcNow,
        });
    }
}
