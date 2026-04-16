using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Interfaces;
using Microsoft.Extensions.Logging;

namespace MarketAnalysis.Infrastructure.Services;

public class PredictionEvaluationService : IPredictionEvaluationService
{
    private readonly IAiPredictionRepository _predictionRepo;
    private readonly IPriceHistoryRepository _priceRepo;
    private readonly ILogger<PredictionEvaluationService> _logger;
    private const double NeutralThreshold = 0.005;

    public PredictionEvaluationService(
        IAiPredictionRepository predictionRepo,
        IPriceHistoryRepository priceRepo,
        ILogger<PredictionEvaluationService> logger)
    {
        _predictionRepo = predictionRepo;
        _priceRepo = priceRepo;
        _logger = logger;
    }

    public async Task EvaluateAsync(CancellationToken cancellationToken = default)
    {
        _logger.LogInformation("Starting AI prediction evaluation");

        await EvaluateHorizonAsync(5, cancellationToken);
        await EvaluateHorizonAsync(10, cancellationToken);
        await EvaluateHorizonAsync(30, cancellationToken);

        _logger.LogInformation("AI prediction evaluation complete");
    }

    private async Task EvaluateHorizonAsync(int horizonDays, CancellationToken cancellationToken)
    {
        var predictions = await _predictionRepo.GetUnevaluatedAsync(horizonDays);
        _logger.LogInformation("Evaluating {Count} predictions at {Horizon} day horizon", predictions.Count, horizonDays);

        foreach (var prediction in predictions)
        {
            if (cancellationToken.IsCancellationRequested) break;

            try
            {
                var evaluationDate = prediction.PredictionDate.AddDays(horizonDays);
                var prices = await _priceRepo.GetByStockAndDateRangeAsync(
                    prediction.StockId, evaluationDate, evaluationDate.AddDays(5));

                if (!prices.Any())
                {
                    _logger.LogWarning("No price data for stock {StockId} at {Date}, skipping",
                        prediction.StockId, evaluationDate);
                    continue;
                }

                var actualPrice = prices.First().Close;
                var changePct = (actualPrice - prediction.EntryPrice) / prediction.EntryPrice;

                // Neutral threshold 0.5%: daily noise typically ±0.3%; 0.5% above noise floor distinguishes flat from directional movement
                string outcome;
                if (Math.Abs((double)changePct) < NeutralThreshold)
                {
                    outcome = "neutral";
                }
                else
                {
                    var actualDirection = changePct > 0 ? "bullish" : "bearish";
                    outcome = actualDirection.Equals(prediction.PredictedDirection, StringComparison.OrdinalIgnoreCase)
                        ? "hit" : "miss";
                }

                if (horizonDays == 5)
                {
                    prediction.ActualPriceAt5Days = actualPrice;
                    prediction.OutcomeAt5Days = outcome;
                }
                else if (horizonDays == 10)
                {
                    prediction.ActualPriceAt10Days = actualPrice;
                    prediction.OutcomeAt10Days = outcome;
                }
                else if (horizonDays == 30)
                {
                    prediction.ActualPriceAt30Days = actualPrice;
                    prediction.OutcomeAt30Days = outcome;
                }

                prediction.EvaluatedAt = DateTime.UtcNow;
                await _predictionRepo.UpdateAsync(prediction);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to evaluate prediction {Id} at {Horizon} days", prediction.Id, horizonDays);
            }
        }
    }

    public async Task<PredictionAccuracyDto> GetAccuracyAsync()
    {
        return await _predictionRepo.GetAccuracyStatsAsync();
    }
}
