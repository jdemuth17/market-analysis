using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Enums;

namespace MarketAnalysis.Core.Interfaces;

/// <summary>HTTP client for communicating with the Python FastAPI service.</summary>
public interface IPythonServiceClient
{
    Task<FetchPricesResponseDto> FetchPricesAsync(List<string> tickers, string period = "6mo", string interval = "1d");
    Task<FetchFundamentalsResponseDto> FetchFundamentalsAsync(List<string> tickers);
    Task<TechnicalAnalysisResponseDto> RunFullTechnicalAnalysisAsync(
        string ticker, List<OHLCVBarDto> bars,
        List<IndicatorType> indicators, List<PatternType> patterns, int lookbackDays = 120);
    Task<FullSentimentResponseDto> RunSentimentPipelineAsync(
        List<string> tickers, List<SentimentSource> sources, int maxItemsPerSource = 30);
    Task<FundamentalScoreDto> ScoreFundamentalsAsync(FundamentalDataDto data);
    Task<List<string>> GetTickerListAsync(string indexName);
    Task<bool> HealthCheckAsync();
}

/// <summary>Orchestrates data ingestion from Python service to database.</summary>
public interface IMarketDataIngestionService
{
    Task IngestPriceDataAsync(List<string> tickers, string period = "6mo");
    Task IngestFundamentalsAsync(List<string> tickers);
    Task IngestTechnicalsAsync(List<string> tickers, Entities.UserScanConfig config);
    Task IngestSentimentAsync(List<string> tickers, Entities.UserScanConfig config);
}

/// <summary>Generates scan reports by scoring and classifying stocks.</summary>
public interface IReportGenerationService
{
    Task<List<Entities.ScanReport>> GenerateReportsAsync(Entities.UserScanConfig config, DateOnly reportDate);
}

/// <summary>Runs the full daily scan pipeline.</summary>
public interface IDailyScanService
{
    Task RunFullScanAsync(CancellationToken cancellationToken = default);
}
