using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.ChangeTracking;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;

namespace MarketAnalysis.Infrastructure.Data;

public class MarketAnalysisDbContext : DbContext
{
    public MarketAnalysisDbContext(DbContextOptions<MarketAnalysisDbContext> options)
        : base(options) { }

    public DbSet<Stock> Stocks => Set<Stock>();
    public DbSet<PriceHistory> PriceHistories => Set<PriceHistory>();
    public DbSet<TechnicalSignal> TechnicalSignals => Set<TechnicalSignal>();
    public DbSet<FundamentalSnapshot> FundamentalSnapshots => Set<FundamentalSnapshot>();
    public DbSet<SentimentScore> SentimentScores => Set<SentimentScore>();
    public DbSet<ScanReport> ScanReports => Set<ScanReport>();
    public DbSet<ScanReportEntry> ScanReportEntries => Set<ScanReportEntry>();
    public DbSet<UserScanConfig> UserScanConfigs => Set<UserScanConfig>();
    public DbSet<WatchList> WatchLists => Set<WatchList>();
    public DbSet<WatchListItem> WatchListItems => Set<WatchListItem>();
    public DbSet<IndexDefinition> IndexDefinitions => Set<IndexDefinition>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // --- Stock ---
        modelBuilder.Entity<Stock>(entity =>
        {
            entity.HasIndex(e => e.Ticker).IsUnique();
            entity.Property(e => e.Ticker).HasMaxLength(10).IsRequired();
            entity.Property(e => e.Name).HasMaxLength(200);
            entity.Property(e => e.Sector).HasMaxLength(100);
            entity.Property(e => e.Industry).HasMaxLength(100);
            entity.Property(e => e.Exchange).HasMaxLength(20);
            entity.Property(e => e.MarketCap).HasColumnType("decimal(18,2)");
        });

        // --- PriceHistory ---
        modelBuilder.Entity<PriceHistory>(entity =>
        {
            entity.HasIndex(e => new { e.StockId, e.Date }).IsUnique();
            entity.HasIndex(e => e.Date);
            entity.Property(e => e.Open).HasColumnType("decimal(18,4)");
            entity.Property(e => e.High).HasColumnType("decimal(18,4)");
            entity.Property(e => e.Low).HasColumnType("decimal(18,4)");
            entity.Property(e => e.Close).HasColumnType("decimal(18,4)");
            entity.Property(e => e.AdjClose).HasColumnType("decimal(18,4)");

            entity.HasOne(e => e.Stock)
                .WithMany(s => s.PriceHistories)
                .HasForeignKey(e => e.StockId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        // --- TechnicalSignal ---
        modelBuilder.Entity<TechnicalSignal>(entity =>
        {
            entity.HasIndex(e => new { e.StockId, e.DetectedDate });

            entity.Property(e => e.PatternType)
                .HasConversion(new EnumToStringConverter<PatternType>());
            entity.Property(e => e.Direction)
                .HasConversion(new EnumToStringConverter<SignalDirection>());

            entity.Property(e => e.KeyPriceLevels).HasColumnType("jsonb");
            entity.Property(e => e.Metadata).HasColumnType("jsonb");

            entity.HasOne(e => e.Stock)
                .WithMany(s => s.TechnicalSignals)
                .HasForeignKey(e => e.StockId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        // --- FundamentalSnapshot ---
        modelBuilder.Entity<FundamentalSnapshot>(entity =>
        {
            entity.HasIndex(e => new { e.StockId, e.SnapshotDate });

            entity.Property(e => e.FreeCashFlow).HasColumnType("decimal(18,2)");
            entity.Property(e => e.Revenue).HasColumnType("decimal(18,2)");
            entity.Property(e => e.MarketCap).HasColumnType("decimal(18,2)");
            entity.Property(e => e.FiftyTwoWeekHigh).HasColumnType("decimal(18,4)");
            entity.Property(e => e.FiftyTwoWeekLow).HasColumnType("decimal(18,4)");
            entity.Property(e => e.CurrentPrice).HasColumnType("decimal(18,4)");
            entity.Property(e => e.TargetMeanPrice).HasColumnType("decimal(18,4)");
            entity.Property(e => e.RawData).HasColumnType("jsonb");

            entity.HasOne(e => e.Stock)
                .WithMany(s => s.FundamentalSnapshots)
                .HasForeignKey(e => e.StockId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        // --- SentimentScore ---
        modelBuilder.Entity<SentimentScore>(entity =>
        {
            entity.HasIndex(e => new { e.StockId, e.AnalysisDate, e.Source });

            entity.Property(e => e.Source)
                .HasConversion(new EnumToStringConverter<SentimentSource>());
            entity.Property(e => e.Headlines).HasColumnType("jsonb");

            entity.HasOne(e => e.Stock)
                .WithMany(s => s.SentimentScores)
                .HasForeignKey(e => e.StockId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        // --- ScanReport ---
        modelBuilder.Entity<ScanReport>(entity =>
        {
            entity.HasIndex(e => new { e.ReportDate, e.Category });

            entity.Property(e => e.Category)
                .HasConversion(new EnumToStringConverter<ReportCategory>());
            entity.Property(e => e.ConfigSnapshot).HasColumnType("jsonb");
        });

        // --- ScanReportEntry ---
        modelBuilder.Entity<ScanReportEntry>(entity =>
        {
            entity.Property(e => e.Reasoning).HasColumnType("jsonb");

            entity.HasOne(e => e.ScanReport)
                .WithMany(r => r.Entries)
                .HasForeignKey(e => e.ScanReportId)
                .OnDelete(DeleteBehavior.Cascade);

            entity.HasOne(e => e.Stock)
                .WithMany(s => s.ScanReportEntries)
                .HasForeignKey(e => e.StockId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        // --- UserScanConfig ---
        modelBuilder.Entity<UserScanConfig>(entity =>
        {
            entity.Property(e => e.Name).HasMaxLength(100).IsRequired();
            entity.Property(e => e.PriceRangeMin).HasColumnType("decimal(18,4)");
            entity.Property(e => e.PriceRangeMax).HasColumnType("decimal(18,4)");
            entity.Property(e => e.MinMarketCap).HasColumnType("decimal(18,2)");

            // Store enum arrays as text arrays in PostgreSQL
            entity.Property(e => e.EnabledPatterns)
                .HasConversion(
                    v => v.Select(p => p.ToString()).ToArray(),
                    v => v.Select(s => Enum.Parse<PatternType>(s)).ToArray()
                )
                .Metadata.SetValueComparer(new ValueComparer<PatternType[]>(
                    (a, b) => a != null && b != null && a.SequenceEqual(b),
                    c => c.Aggregate(0, (a, v) => HashCode.Combine(a, v.GetHashCode())),
                    c => c.ToArray()));
            entity.Property(e => e.EnabledCategories)
                .HasConversion(
                    v => v.Select(c => c.ToString()).ToArray(),
                    v => v.Select(s => Enum.Parse<ReportCategory>(s)).ToArray()
                )
                .Metadata.SetValueComparer(new ValueComparer<ReportCategory[]>(
                    (a, b) => a != null && b != null && a.SequenceEqual(b),
                    c => c.Aggregate(0, (a, v) => HashCode.Combine(a, v.GetHashCode())),
                    c => c.ToArray()));
            entity.Property(e => e.EnabledSentimentSources)
                .HasConversion(
                    v => v.Select(s => s.ToString()).ToArray(),
                    v => v.Select(s => Enum.Parse<SentimentSource>(s)).ToArray()
                )
                .Metadata.SetValueComparer(new ValueComparer<SentimentSource[]>(
                    (a, b) => a != null && b != null && a.SequenceEqual(b),
                    c => c.Aggregate(0, (a, v) => HashCode.Combine(a, v.GetHashCode())),
                    c => c.ToArray()));
            entity.Property(e => e.EnabledIndicators)
                .HasConversion(
                    v => v.Select(i => i.ToString()).ToArray(),
                    v => v.Select(s => Enum.Parse<IndicatorType>(s)).ToArray()
                )
                .Metadata.SetValueComparer(new ValueComparer<IndicatorType[]>(
                    (a, b) => a != null && b != null && a.SequenceEqual(b),
                    c => c.Aggregate(0, (a, v) => HashCode.Combine(a, v.GetHashCode())),
                    c => c.ToArray()));
        });

        // --- WatchList ---
        modelBuilder.Entity<WatchList>(entity =>
        {
            entity.Property(e => e.Name).HasMaxLength(100).IsRequired();
            entity.Property(e => e.Description).HasMaxLength(500);
        });

        // --- WatchListItem ---
        modelBuilder.Entity<WatchListItem>(entity =>
        {
            entity.HasIndex(e => new { e.WatchListId, e.StockId }).IsUnique();

            entity.HasOne(e => e.WatchList)
                .WithMany(w => w.Items)
                .HasForeignKey(e => e.WatchListId)
                .OnDelete(DeleteBehavior.Cascade);

            entity.HasOne(e => e.Stock)
                .WithMany(s => s.WatchListItems)
                .HasForeignKey(e => e.StockId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        // --- IndexDefinition ---
        modelBuilder.Entity<IndexDefinition>(entity =>
        {
            entity.HasIndex(e => e.Name).IsUnique();
            entity.Property(e => e.Name).HasMaxLength(50).IsRequired();
        });

        // Seed default data
        SeedData(modelBuilder);
    }

    private static void SeedData(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<UserScanConfig>().HasData(new UserScanConfig
        {
            Id = 1,
            Name = "Default",
            IsDefault = true,
            PriceRangeMin = 5m,
            PriceRangeMax = 500m,
            MaxPERatio = 50,
            MaxDebtToEquity = 200,
            MinProfitMargin = 0.05,
            MinSentimentSampleSize = 3,
            TechnicalWeight = 0.40,
            FundamentalWeight = 0.35,
            SentimentWeight = 0.25,
            EnabledPatterns = Enum.GetValues<PatternType>(),
            EnabledCategories = Enum.GetValues<ReportCategory>(),
            EnabledSentimentSources = Enum.GetValues<SentimentSource>(),
            EnabledIndicators = new[]
            {
                IndicatorType.RSI14, IndicatorType.MACD, IndicatorType.SMA50,
                IndicatorType.SMA200, IndicatorType.BollingerBands, IndicatorType.ATR, IndicatorType.OBV,
            },
        });

        modelBuilder.Entity<IndexDefinition>().HasData(
            new IndexDefinition { Id = 1, Name = "S&P 500", IsEnabled = false, Tickers = Array.Empty<string>() },
            new IndexDefinition { Id = 2, Name = "NASDAQ 100", IsEnabled = false, Tickers = Array.Empty<string>() }
        );
    }
}
