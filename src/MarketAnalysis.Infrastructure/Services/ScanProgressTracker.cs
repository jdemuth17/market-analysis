using MarketAnalysis.Core.Interfaces;

namespace MarketAnalysis.Infrastructure.Services;

public class ScanProgressTracker : IScanProgressTracker
{
    private readonly object _lock = new();

    public bool IsRunning { get; private set; }
    public string CurrentStep { get; private set; } = "";
    public int CurrentStepNumber { get; private set; }
    public int TotalSteps { get; private set; }
    public int TickersProcessed { get; private set; }
    public int TotalTickers { get; private set; }
    public DateTime? StartedAtUtc { get; private set; }
    public DateTime? CompletedAtUtc { get; private set; }
    public string? ErrorMessage { get; private set; }

    public double OverallPercentage
    {
        get
        {
            if (TotalSteps == 0) return 0;
            double stepWeight = 100.0 / TotalSteps;
            double completedSteps = Math.Max(0, CurrentStepNumber - 1) * stepWeight;
            double currentStepProgress = TotalTickers > 0
                ? (double)TickersProcessed / TotalTickers * stepWeight
                : 0;
            return Math.Min(completedSteps + currentStepProgress, 100);
        }
    }

    public void Start(int totalTickers, int totalSteps = 6)
    {
        lock (_lock)
        {
            IsRunning = true;
            TotalTickers = totalTickers;
            TotalSteps = totalSteps;
            TickersProcessed = 0;
            CurrentStepNumber = 0;
            CurrentStep = "Starting...";
            StartedAtUtc = DateTime.UtcNow;
            CompletedAtUtc = null;
            ErrorMessage = null;
        }
    }

    public void SetStep(int stepNumber, string stepName)
    {
        lock (_lock)
        {
            CurrentStepNumber = stepNumber;
            CurrentStep = stepName;
            TickersProcessed = 0;
        }
    }

    public void IncrementTicker()
    {
        lock (_lock) { TickersProcessed++; }
    }

    public void Complete()
    {
        lock (_lock)
        {
            IsRunning = false;
            CurrentStep = "Completed";
            CompletedAtUtc = DateTime.UtcNow;
        }
    }

    public void Fail(string errorMessage)
    {
        lock (_lock)
        {
            IsRunning = false;
            CurrentStep = "Failed";
            ErrorMessage = errorMessage;
            CompletedAtUtc = DateTime.UtcNow;
        }
    }
}
