using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

#pragma warning disable CA1814 // Prefer jagged arrays over multidimensional

namespace MarketAnalysis.Infrastructure.Migrations
{
    /// <inheritdoc />
    public partial class Initial : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "IndexDefinitions",
                columns: table => new
                {
                    Id = table.Column<int>(type: "integer", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    Name = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    IsEnabled = table.Column<bool>(type: "boolean", nullable: false),
                    Tickers = table.Column<string[]>(type: "text[]", nullable: false),
                    LastRefreshedUtc = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_IndexDefinitions", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "ScanReports",
                columns: table => new
                {
                    Id = table.Column<int>(type: "integer", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    ReportDate = table.Column<DateOnly>(type: "date", nullable: false),
                    Category = table.Column<string>(type: "text", nullable: false),
                    GeneratedAtUtc = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    ConfigSnapshot = table.Column<string>(type: "jsonb", nullable: false),
                    TotalStocksScanned = table.Column<int>(type: "integer", nullable: false),
                    TotalMatches = table.Column<int>(type: "integer", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_ScanReports", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "Stocks",
                columns: table => new
                {
                    Id = table.Column<int>(type: "integer", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    Ticker = table.Column<string>(type: "character varying(10)", maxLength: 10, nullable: false),
                    Name = table.Column<string>(type: "character varying(200)", maxLength: 200, nullable: false),
                    Sector = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    Industry = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    Exchange = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: true),
                    MarketCap = table.Column<decimal>(type: "numeric(18,2)", nullable: true),
                    IsActive = table.Column<bool>(type: "boolean", nullable: false),
                    LastUpdatedUtc = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Stocks", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "UserScanConfigs",
                columns: table => new
                {
                    Id = table.Column<int>(type: "integer", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    Name = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    IsDefault = table.Column<bool>(type: "boolean", nullable: false),
                    EnabledPatterns = table.Column<string[]>(type: "text[]", nullable: false),
                    PriceRangeMin = table.Column<decimal>(type: "numeric(18,4)", nullable: true),
                    PriceRangeMax = table.Column<decimal>(type: "numeric(18,4)", nullable: true),
                    MinMarketCap = table.Column<decimal>(type: "numeric(18,2)", nullable: true),
                    MaxPERatio = table.Column<double>(type: "double precision", nullable: true),
                    MaxDebtToEquity = table.Column<double>(type: "double precision", nullable: true),
                    MinProfitMargin = table.Column<double>(type: "double precision", nullable: true),
                    MinSentimentScore = table.Column<double>(type: "double precision", nullable: true),
                    MinSentimentSampleSize = table.Column<int>(type: "integer", nullable: false),
                    TechnicalWeight = table.Column<double>(type: "double precision", nullable: false),
                    FundamentalWeight = table.Column<double>(type: "double precision", nullable: false),
                    SentimentWeight = table.Column<double>(type: "double precision", nullable: false),
                    EnabledCategories = table.Column<string[]>(type: "text[]", nullable: false),
                    EnabledSentimentSources = table.Column<string[]>(type: "text[]", nullable: false),
                    EnabledIndicators = table.Column<string[]>(type: "text[]", nullable: false),
                    CreatedAtUtc = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    UpdatedAtUtc = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_UserScanConfigs", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "WatchLists",
                columns: table => new
                {
                    Id = table.Column<int>(type: "integer", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    Name = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    Description = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true),
                    CreatedAtUtc = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_WatchLists", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "FundamentalSnapshots",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    StockId = table.Column<int>(type: "integer", nullable: false),
                    SnapshotDate = table.Column<DateOnly>(type: "date", nullable: false),
                    PeRatio = table.Column<double>(type: "double precision", nullable: true),
                    ForwardPe = table.Column<double>(type: "double precision", nullable: true),
                    PegRatio = table.Column<double>(type: "double precision", nullable: true),
                    PriceToBook = table.Column<double>(type: "double precision", nullable: true),
                    RevenuePerShare = table.Column<double>(type: "double precision", nullable: true),
                    EarningsPerShare = table.Column<double>(type: "double precision", nullable: true),
                    DebtToEquity = table.Column<double>(type: "double precision", nullable: true),
                    ProfitMargin = table.Column<double>(type: "double precision", nullable: true),
                    OperatingMargin = table.Column<double>(type: "double precision", nullable: true),
                    ReturnOnEquity = table.Column<double>(type: "double precision", nullable: true),
                    FreeCashFlow = table.Column<decimal>(type: "numeric(18,2)", nullable: true),
                    DividendYield = table.Column<double>(type: "double precision", nullable: true),
                    Revenue = table.Column<decimal>(type: "numeric(18,2)", nullable: true),
                    MarketCap = table.Column<decimal>(type: "numeric(18,2)", nullable: true),
                    Beta = table.Column<double>(type: "double precision", nullable: true),
                    FiftyTwoWeekHigh = table.Column<decimal>(type: "numeric(18,4)", nullable: true),
                    FiftyTwoWeekLow = table.Column<decimal>(type: "numeric(18,4)", nullable: true),
                    CurrentPrice = table.Column<decimal>(type: "numeric(18,4)", nullable: true),
                    TargetMeanPrice = table.Column<decimal>(type: "numeric(18,4)", nullable: true),
                    RecommendationKey = table.Column<string>(type: "text", nullable: true),
                    ValueScore = table.Column<double>(type: "double precision", nullable: false),
                    QualityScore = table.Column<double>(type: "double precision", nullable: false),
                    GrowthScore = table.Column<double>(type: "double precision", nullable: false),
                    SafetyScore = table.Column<double>(type: "double precision", nullable: false),
                    CompositeScore = table.Column<double>(type: "double precision", nullable: false),
                    RawData = table.Column<string>(type: "jsonb", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_FundamentalSnapshots", x => x.Id);
                    table.ForeignKey(
                        name: "FK_FundamentalSnapshots_Stocks_StockId",
                        column: x => x.StockId,
                        principalTable: "Stocks",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "PriceHistories",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    StockId = table.Column<int>(type: "integer", nullable: false),
                    Date = table.Column<DateOnly>(type: "date", nullable: false),
                    Open = table.Column<decimal>(type: "numeric(18,4)", nullable: false),
                    High = table.Column<decimal>(type: "numeric(18,4)", nullable: false),
                    Low = table.Column<decimal>(type: "numeric(18,4)", nullable: false),
                    Close = table.Column<decimal>(type: "numeric(18,4)", nullable: false),
                    AdjClose = table.Column<decimal>(type: "numeric(18,4)", nullable: false),
                    Volume = table.Column<long>(type: "bigint", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_PriceHistories", x => x.Id);
                    table.ForeignKey(
                        name: "FK_PriceHistories_Stocks_StockId",
                        column: x => x.StockId,
                        principalTable: "Stocks",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "ScanReportEntries",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    ScanReportId = table.Column<int>(type: "integer", nullable: false),
                    StockId = table.Column<int>(type: "integer", nullable: false),
                    CompositeScore = table.Column<double>(type: "double precision", nullable: false),
                    TechnicalScore = table.Column<double>(type: "double precision", nullable: false),
                    FundamentalScore = table.Column<double>(type: "double precision", nullable: false),
                    SentimentScore = table.Column<double>(type: "double precision", nullable: false),
                    Rank = table.Column<int>(type: "integer", nullable: false),
                    CurrentPrice = table.Column<decimal>(type: "numeric", nullable: true),
                    PatternDetected = table.Column<string>(type: "text", nullable: true),
                    Direction = table.Column<string>(type: "text", nullable: true),
                    Reasoning = table.Column<string>(type: "jsonb", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_ScanReportEntries", x => x.Id);
                    table.ForeignKey(
                        name: "FK_ScanReportEntries_ScanReports_ScanReportId",
                        column: x => x.ScanReportId,
                        principalTable: "ScanReports",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_ScanReportEntries_Stocks_StockId",
                        column: x => x.StockId,
                        principalTable: "Stocks",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "SentimentScores",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    StockId = table.Column<int>(type: "integer", nullable: false),
                    AnalysisDate = table.Column<DateOnly>(type: "date", nullable: false),
                    Source = table.Column<string>(type: "text", nullable: false),
                    PositiveScore = table.Column<double>(type: "double precision", nullable: false),
                    NegativeScore = table.Column<double>(type: "double precision", nullable: false),
                    NeutralScore = table.Column<double>(type: "double precision", nullable: false),
                    SampleSize = table.Column<int>(type: "integer", nullable: false),
                    Headlines = table.Column<string>(type: "jsonb", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_SentimentScores", x => x.Id);
                    table.ForeignKey(
                        name: "FK_SentimentScores_Stocks_StockId",
                        column: x => x.StockId,
                        principalTable: "Stocks",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "TechnicalSignals",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    StockId = table.Column<int>(type: "integer", nullable: false),
                    DetectedDate = table.Column<DateOnly>(type: "date", nullable: false),
                    PatternType = table.Column<string>(type: "text", nullable: false),
                    Direction = table.Column<string>(type: "text", nullable: false),
                    Confidence = table.Column<double>(type: "double precision", nullable: false),
                    StartDate = table.Column<DateOnly>(type: "date", nullable: false),
                    EndDate = table.Column<DateOnly>(type: "date", nullable: false),
                    Status = table.Column<string>(type: "text", nullable: false),
                    KeyPriceLevels = table.Column<string>(type: "jsonb", nullable: false),
                    Metadata = table.Column<string>(type: "jsonb", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_TechnicalSignals", x => x.Id);
                    table.ForeignKey(
                        name: "FK_TechnicalSignals_Stocks_StockId",
                        column: x => x.StockId,
                        principalTable: "Stocks",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "WatchListItems",
                columns: table => new
                {
                    Id = table.Column<int>(type: "integer", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    WatchListId = table.Column<int>(type: "integer", nullable: false),
                    StockId = table.Column<int>(type: "integer", nullable: false),
                    AddedAtUtc = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_WatchListItems", x => x.Id);
                    table.ForeignKey(
                        name: "FK_WatchListItems_Stocks_StockId",
                        column: x => x.StockId,
                        principalTable: "Stocks",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_WatchListItems_WatchLists_WatchListId",
                        column: x => x.WatchListId,
                        principalTable: "WatchLists",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.InsertData(
                table: "IndexDefinitions",
                columns: new[] { "Id", "IsEnabled", "LastRefreshedUtc", "Name", "Tickers" },
                values: new object[,]
                {
                    { 1, false, new DateTime(2026, 2, 9, 14, 55, 13, 210, DateTimeKind.Utc).AddTicks(9501), "S&P 500", new string[0] },
                    { 2, false, new DateTime(2026, 2, 9, 14, 55, 13, 210, DateTimeKind.Utc).AddTicks(9503), "NASDAQ 100", new string[0] }
                });

            migrationBuilder.InsertData(
                table: "UserScanConfigs",
                columns: new[] { "Id", "CreatedAtUtc", "EnabledCategories", "EnabledIndicators", "EnabledPatterns", "EnabledSentimentSources", "FundamentalWeight", "IsDefault", "MaxDebtToEquity", "MaxPERatio", "MinMarketCap", "MinProfitMargin", "MinSentimentSampleSize", "MinSentimentScore", "Name", "PriceRangeMax", "PriceRangeMin", "SentimentWeight", "TechnicalWeight", "UpdatedAtUtc" },
                values: new object[] { 1, new DateTime(2026, 2, 9, 14, 55, 13, 210, DateTimeKind.Utc).AddTicks(9089), new[] { "DayTrade", "SwingTrade", "ShortTermHold", "LongTermHold" }, new[] { "RSI14", "MACD", "SMA50", "SMA200", "BollingerBands", "ATR", "OBV" }, new[] { "DoubleTop", "DoubleBottom", "HeadAndShoulders", "InverseHeadAndShoulders", "BullFlag", "BearFlag", "AscendingTriangle", "DescendingTriangle", "SymmetricalTriangle", "RisingWedge", "FallingWedge", "Pennant", "CupAndHandle" }, new[] { "News", "Reddit", "StockTwits" }, 0.34999999999999998, true, 200.0, 50.0, null, 0.050000000000000003, 3, null, "Default", 500m, 5m, 0.25, 0.40000000000000002, new DateTime(2026, 2, 9, 14, 55, 13, 210, DateTimeKind.Utc).AddTicks(9091) });

            migrationBuilder.CreateIndex(
                name: "IX_FundamentalSnapshots_StockId_SnapshotDate",
                table: "FundamentalSnapshots",
                columns: new[] { "StockId", "SnapshotDate" });

            migrationBuilder.CreateIndex(
                name: "IX_IndexDefinitions_Name",
                table: "IndexDefinitions",
                column: "Name",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_PriceHistories_Date",
                table: "PriceHistories",
                column: "Date");

            migrationBuilder.CreateIndex(
                name: "IX_PriceHistories_StockId_Date",
                table: "PriceHistories",
                columns: new[] { "StockId", "Date" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_ScanReportEntries_ScanReportId",
                table: "ScanReportEntries",
                column: "ScanReportId");

            migrationBuilder.CreateIndex(
                name: "IX_ScanReportEntries_StockId",
                table: "ScanReportEntries",
                column: "StockId");

            migrationBuilder.CreateIndex(
                name: "IX_ScanReports_ReportDate_Category",
                table: "ScanReports",
                columns: new[] { "ReportDate", "Category" });

            migrationBuilder.CreateIndex(
                name: "IX_SentimentScores_StockId_AnalysisDate_Source",
                table: "SentimentScores",
                columns: new[] { "StockId", "AnalysisDate", "Source" });

            migrationBuilder.CreateIndex(
                name: "IX_Stocks_Ticker",
                table: "Stocks",
                column: "Ticker",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_TechnicalSignals_StockId_DetectedDate",
                table: "TechnicalSignals",
                columns: new[] { "StockId", "DetectedDate" });

            migrationBuilder.CreateIndex(
                name: "IX_WatchListItems_StockId",
                table: "WatchListItems",
                column: "StockId");

            migrationBuilder.CreateIndex(
                name: "IX_WatchListItems_WatchListId_StockId",
                table: "WatchListItems",
                columns: new[] { "WatchListId", "StockId" },
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "FundamentalSnapshots");

            migrationBuilder.DropTable(
                name: "IndexDefinitions");

            migrationBuilder.DropTable(
                name: "PriceHistories");

            migrationBuilder.DropTable(
                name: "ScanReportEntries");

            migrationBuilder.DropTable(
                name: "SentimentScores");

            migrationBuilder.DropTable(
                name: "TechnicalSignals");

            migrationBuilder.DropTable(
                name: "UserScanConfigs");

            migrationBuilder.DropTable(
                name: "WatchListItems");

            migrationBuilder.DropTable(
                name: "ScanReports");

            migrationBuilder.DropTable(
                name: "Stocks");

            migrationBuilder.DropTable(
                name: "WatchLists");
        }
    }
}
