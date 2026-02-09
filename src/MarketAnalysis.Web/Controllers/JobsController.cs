using MarketAnalysis.Core.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace MarketAnalysis.Web.Controllers;

[ApiController]
[Route("api/[controller]")]
public class JobsController : ControllerBase
{
    private readonly IDailyScanService _scanService;
    private readonly IPythonServiceClient _python;

    public JobsController(IDailyScanService scanService, IPythonServiceClient python)
    {
        _scanService = scanService;
        _python = python;
    }

    /// <summary>Trigger a full scan manually.</summary>
    [HttpPost("trigger-scan")]
    public async Task<ActionResult> TriggerScan()
    {
        // Run in background so the API returns immediately
        _ = Task.Run(async () =>
        {
            try { await _scanService.RunFullScanAsync(); }
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
