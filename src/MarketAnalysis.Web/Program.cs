using Hangfire;
using Hangfire.PostgreSql;
using MarketAnalysis.Core.Interfaces;
using MarketAnalysis.Infrastructure.Data;
using MarketAnalysis.Infrastructure.Repositories;
using MarketAnalysis.Infrastructure.Services;
using MarketAnalysis.Web.Components;
using Microsoft.EntityFrameworkCore;
using MudBlazor.Services;
using Polly;
using Polly.Extensions.Http;

var builder = WebApplication.CreateBuilder(args);
var config = builder.Configuration;

// ----- Database -----
builder.Services.AddDbContext<MarketAnalysisDbContext>(opts =>
    opts.UseNpgsql(config.GetConnectionString("DefaultConnection")));

// ----- Repositories -----
builder.Services.AddScoped<IStockRepository, StockRepository>();
builder.Services.AddScoped<IPriceHistoryRepository, PriceHistoryRepository>();
builder.Services.AddScoped<ITechnicalSignalRepository, TechnicalSignalRepository>();
builder.Services.AddScoped<IFundamentalRepository, FundamentalRepository>();
builder.Services.AddScoped<ISentimentRepository, SentimentRepository>();
builder.Services.AddScoped<IScanReportRepository, ScanReportRepository>();
builder.Services.AddScoped<IWatchListRepository, WatchListRepository>();
builder.Services.AddScoped<IUserScanConfigRepository, UserScanConfigRepository>();
builder.Services.AddScoped<IIndexDefinitionRepository, IndexDefinitionRepository>();

// ----- Python Service HTTP Client with Polly -----
builder.Services.AddHttpClient<IPythonServiceClient, PythonServiceClient>(client =>
{
    client.BaseAddress = new Uri(config["PythonService:BaseUrl"] ?? "http://localhost:8000");
    client.Timeout = TimeSpan.FromMinutes(5);
})
.AddPolicyHandler(HttpPolicyExtensions
    .HandleTransientHttpError()
    .WaitAndRetryAsync(3, i => TimeSpan.FromSeconds(Math.Pow(2, i))))
.AddPolicyHandler(HttpPolicyExtensions
    .HandleTransientHttpError()
    .CircuitBreakerAsync(5, TimeSpan.FromSeconds(30)));

// ----- ML Service HTTP Client with Polly -----
builder.Services.AddHttpClient<IMLServiceClient, MLServiceClient>(client =>
{
    client.BaseAddress = new Uri(config["MLService:BaseUrl"] ?? "http://localhost:8002");
    client.Timeout = TimeSpan.FromMinutes(2);
})
.AddPolicyHandler(HttpPolicyExtensions
    .HandleTransientHttpError()
    .WaitAndRetryAsync(3, i => TimeSpan.FromSeconds(Math.Pow(2, i))))
.AddPolicyHandler(HttpPolicyExtensions
    .HandleTransientHttpError()
    .CircuitBreakerAsync(5, TimeSpan.FromSeconds(30)));

// ----- Business Services -----
builder.Services.AddScoped<IMarketDataIngestionService, MarketDataIngestionService>();
builder.Services.AddScoped<IReportGenerationService, ReportGenerationService>();
builder.Services.AddScoped<IDailyScanService, DailyScanService>();

// ----- ML Retraining Service (reuses ML Service HTTP client) -----
builder.Services.AddHttpClient<IMLRetrainingService, MLRetrainingService>(client =>
{
    client.BaseAddress = new Uri(config["MLService:BaseUrl"] ?? "http://localhost:8002");
    client.Timeout = TimeSpan.FromMinutes(130); // Long timeout for backfill + training
})
.AddPolicyHandler(HttpPolicyExtensions
    .HandleTransientHttpError()
    .WaitAndRetryAsync(3, i => TimeSpan.FromSeconds(Math.Pow(2, i))))
.AddPolicyHandler(HttpPolicyExtensions
    .HandleTransientHttpError()
    .CircuitBreakerAsync(5, TimeSpan.FromSeconds(30)));

// ----- Hangfire -----
builder.Services.AddHangfire(hf => hf
    .SetDataCompatibilityLevel(CompatibilityLevel.Version_180)
    .UseSimpleAssemblyNameTypeSerializer()
    .UseRecommendedSerializerSettings()
    .UsePostgreSqlStorage(opts =>
        opts.UseNpgsqlConnection(config.GetConnectionString("DefaultConnection"))));
builder.Services.AddHangfireServer();

// ----- MudBlazor -----
builder.Services.AddMudServices();

// ----- API Controllers -----
builder.Services.AddControllers();

// ----- Blazor -----
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

var app = builder.Build();

// ----- Auto-migrate database -----
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<MarketAnalysisDbContext>();
    await db.Database.MigrateAsync();
}

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error", createScopeForErrors: true);
    app.UseHsts();
}

app.UseHttpsRedirection();
app.UseStaticFiles();
app.UseAntiforgery();

// ----- API endpoints -----
app.MapControllers();

// ----- Hangfire dashboard -----
app.MapHangfireDashboard("/hangfire");

// ----- Schedule recurring jobs -----
RecurringJob.AddOrUpdate<IDailyScanService>(
    "daily-market-scan",
    service => service.RunFullScanAsync(CancellationToken.None),
    "0 18 * * 1-5", // 6:00 PM UTC weekdays (adjust to your timezone)
    new RecurringJobOptions { TimeZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time") });

// Weekly ML retrain: Sundays at 2 AM ET — XGBoost + ensemble (fast, ~10 min)
RecurringJob.AddOrUpdate<IMLRetrainingService>(
    "weekly-ml-retrain",
    service => service.RunRetrainingAsync(new List<string> { "xgboost", "ensemble" }, CancellationToken.None),
    "0 2 * * 0",
    new RecurringJobOptions { TimeZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time") });

// Monthly ML retrain: 1st Sunday at 1 AM ET — full XGBoost + LSTM + ensemble (~1 hr)
RecurringJob.AddOrUpdate<IMLRetrainingService>(
    "monthly-ml-retrain",
    service => service.RunRetrainingAsync(new List<string> { "xgboost", "lstm", "ensemble" }, CancellationToken.None),
    "0 1 1-7 * 0",
    new RecurringJobOptions { TimeZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time") });

app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

app.Run();
