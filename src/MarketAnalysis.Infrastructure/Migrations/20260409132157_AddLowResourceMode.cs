using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace MarketAnalysis.Infrastructure.Migrations
{
    /// <inheritdoc />
    public partial class AddLowResourceMode : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<bool>(
                name: "LowResourceMode",
                table: "UserScanConfigs",
                type: "boolean",
                nullable: false,
                defaultValue: false);

            migrationBuilder.UpdateData(
                table: "IndexDefinitions",
                keyColumn: "Id",
                keyValue: 1,
                column: "LastRefreshedUtc",
                value: new DateTime(2026, 4, 9, 13, 21, 56, 747, DateTimeKind.Utc).AddTicks(5750));

            migrationBuilder.UpdateData(
                table: "IndexDefinitions",
                keyColumn: "Id",
                keyValue: 2,
                column: "LastRefreshedUtc",
                value: new DateTime(2026, 4, 9, 13, 21, 56, 747, DateTimeKind.Utc).AddTicks(5752));

            migrationBuilder.UpdateData(
                table: "UserScanConfigs",
                keyColumn: "Id",
                keyValue: 1,
                columns: new[] { "CreatedAtUtc", "LowResourceMode", "UpdatedAtUtc" },
                values: new object[] { new DateTime(2026, 4, 9, 13, 21, 56, 747, DateTimeKind.Utc).AddTicks(5432), false, new DateTime(2026, 4, 9, 13, 21, 56, 747, DateTimeKind.Utc).AddTicks(5434) });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "LowResourceMode",
                table: "UserScanConfigs");

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
                columns: new[] { "CreatedAtUtc", "UpdatedAtUtc" },
                values: new object[] { new DateTime(2026, 2, 11, 13, 50, 56, 130, DateTimeKind.Utc).AddTicks(1005), new DateTime(2026, 2, 11, 13, 50, 56, 130, DateTimeKind.Utc).AddTicks(1007) });
        }
    }
}
