using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace MarketAnalysis.Infrastructure.Migrations
{
    /// <inheritdoc />
    public partial class AddUseMlScoringToUserScanConfig : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<bool>(
                name: "UseMlScoring",
                table: "UserScanConfigs",
                type: "boolean",
                nullable: false,
                defaultValue: false);

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
                columns: new[] { "CreatedAtUtc", "UpdatedAtUtc", "UseMlScoring" },
                values: new object[] { new DateTime(2026, 2, 10, 14, 54, 39, 987, DateTimeKind.Utc).AddTicks(9908), new DateTime(2026, 2, 10, 14, 54, 39, 987, DateTimeKind.Utc).AddTicks(9911), false });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "UseMlScoring",
                table: "UserScanConfigs");

            migrationBuilder.UpdateData(
                table: "IndexDefinitions",
                keyColumn: "Id",
                keyValue: 1,
                column: "LastRefreshedUtc",
                value: new DateTime(2026, 2, 9, 14, 55, 13, 210, DateTimeKind.Utc).AddTicks(9501));

            migrationBuilder.UpdateData(
                table: "IndexDefinitions",
                keyColumn: "Id",
                keyValue: 2,
                column: "LastRefreshedUtc",
                value: new DateTime(2026, 2, 9, 14, 55, 13, 210, DateTimeKind.Utc).AddTicks(9503));

            migrationBuilder.UpdateData(
                table: "UserScanConfigs",
                keyColumn: "Id",
                keyValue: 1,
                columns: new[] { "CreatedAtUtc", "UpdatedAtUtc" },
                values: new object[] { new DateTime(2026, 2, 9, 14, 55, 13, 210, DateTimeKind.Utc).AddTicks(9089), new DateTime(2026, 2, 9, 14, 55, 13, 210, DateTimeKind.Utc).AddTicks(9091) });
        }
    }
}
