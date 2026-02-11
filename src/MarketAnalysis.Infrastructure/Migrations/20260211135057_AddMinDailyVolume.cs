using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace MarketAnalysis.Infrastructure.Migrations
{
    /// <inheritdoc />
    public partial class AddMinDailyVolume : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<long>(
                name: "MinDailyVolume",
                table: "UserScanConfigs",
                type: "bigint",
                nullable: true);

            migrationBuilder.UpdateData(
                table: "IndexDefinitions",
                keyColumn: "Id",
                keyValue: 1,
                column: "LastRefreshedUtc",
                value: new DateTime(2026, 2, 11, 13, 50, 56, 130, DateTimeKind.Utc).AddTicks(1154));

            migrationBuilder.UpdateData(
                table: "IndexDefinitions",
                keyColumn: "Id",
                keyValue: 2,
                column: "LastRefreshedUtc",
                value: new DateTime(2026, 2, 11, 13, 50, 56, 130, DateTimeKind.Utc).AddTicks(1157));

            migrationBuilder.UpdateData(
                table: "UserScanConfigs",
                keyColumn: "Id",
                keyValue: 1,
                columns: new[] { "CreatedAtUtc", "MinDailyVolume", "UpdatedAtUtc" },
                values: new object[] { new DateTime(2026, 2, 11, 13, 50, 56, 130, DateTimeKind.Utc).AddTicks(1005), null, new DateTime(2026, 2, 11, 13, 50, 56, 130, DateTimeKind.Utc).AddTicks(1007) });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "MinDailyVolume",
                table: "UserScanConfigs");

            migrationBuilder.UpdateData(
                table: "IndexDefinitions",
                keyColumn: "Id",
                keyValue: 1,
                column: "LastRefreshedUtc",
                value: new DateTime(2026, 2, 10, 14, 54, 39, 988, DateTimeKind.Utc).AddTicks(430));

            migrationBuilder.UpdateData(
                table: "IndexDefinitions",
                keyColumn: "Id",
                keyValue: 2,
                column: "LastRefreshedUtc",
                value: new DateTime(2026, 2, 10, 14, 54, 39, 988, DateTimeKind.Utc).AddTicks(432));

            migrationBuilder.UpdateData(
                table: "UserScanConfigs",
                keyColumn: "Id",
                keyValue: 1,
                columns: new[] { "CreatedAtUtc", "UpdatedAtUtc" },
                values: new object[] { new DateTime(2026, 2, 10, 14, 54, 39, 987, DateTimeKind.Utc).AddTicks(9908), new DateTime(2026, 2, 10, 14, 54, 39, 987, DateTimeKind.Utc).AddTicks(9911) });
        }
    }
}
