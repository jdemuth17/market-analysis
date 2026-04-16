# AI Analysis & Sentiment Detail Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the UI to show the "Logic and Analysis" behind each stock pick, including AI/ML reasoning and live sentiment headlines.

**Architecture:**
- Create a shared Blazor component `AnalysisReasoning.razor` to visualize the JSON reasoning from the `ScanReportEntry`.
- Update `ReportDetail.razor` with an expandable row to show this reasoning.
- Update `StockDetail.razor` to show the latest reasoning and a list of actual headlines/posts from the sentiment scrapers.
- Refactor DTOs and Repositories as needed to ensure this data is available.

**Tech Stack:** .NET 8, Blazor Server, MudBlazor, ApexCharts.Blazor.

---

### Task 1: Create AnalysisReasoning Component

**Files:**
- Create: `src/MarketAnalysis.Web/Components/Shared/AnalysisReasoning.razor`

- [ ] **Step 1: Implement the component UI**
      This component will parse the `Reasoning` dictionary and display it as a series of cards or a structured list.

```razor
@using System.Text.Json
@inject ISnackbar Snackbar

<MudPaper Elevation="0" Class="pa-4 bg-gray-50 dark:bg-gray-800">
    @if (ReasoningDict == null || !ReasoningDict.Any())
    {
        <MudText Typo="Typo.body2" Color="Color.Secondary">No detailed reasoning available.</MudText>
    }
    else
    {
        <MudGrid>
            <!-- Scoring Method -->
            <MudItem xs="12">
                <MudAlert Severity="Severity.Info" Dense="true" Class="mb-2">
                    Analysis Method: <strong>@GetVal("scoringMethod")</strong>
                </MudAlert>
            </MudItem>

            <!-- ML Drivers if applicable -->
            @if (ReasoningDict.ContainsKey("topDrivers"))
            {
                <MudItem xs="12">
                    <MudText Typo="Typo.subtitle2" Class="mb-2">Key ML Drivers</MudText>
                    @foreach (var driver in GetList("topDrivers"))
                    {
                        <MudText Typo="Typo.body2" Class="ml-4">• @driver</MudText>
                    }
                </MudItem>
            }

            <!-- Legacy Details if applicable -->
            @if (ReasoningDict.ContainsKey("details"))
            {
                <MudItem xs="12">
                    <MudText Typo="Typo.subtitle2" Class="mb-2">Analysis Breakdown</MudText>
                    <MudGrid>
                        @foreach (var detail in GetDict("details"))
                        {
                            <MudItem xs="6" md="4">
                                <MudText Typo="Typo.caption">@detail.Key</MudText>
                                <MudText Typo="Typo.body2"><strong>@detail.Value</strong></MudText>
                            </MudItem>
                        }
                    </MudGrid>
                </MudItem>
            }

            <!-- Scores -->
            <MudItem xs="12" md="4">
                <MudText Typo="Typo.caption">Technical Evidence</MudText>
                <MudProgressLinear Color="Color.Info" Value="@GetDouble("technicalScore")" Class="my-1" />
                <MudText Typo="Typo.body2">@GetDouble("technicalScore").ToString("F1")/100</MudText>
            </MudItem>
            <MudItem xs="12" md="4">
                <MudText Typo="Typo.caption">Fundamental Foundation</MudText>
                <MudProgressLinear Color="Color.Primary" Value="@GetDouble("fundamentalScore")" Class="my-1" />
                <MudText Typo="Typo.body2">@GetDouble("fundamentalScore").ToString("F1")/100</MudText>
            </MudItem>
            <MudItem xs="12" md="4">
                <MudText Typo="Typo.caption">Sentiment/Social Context</MudText>
                <MudProgressLinear Color="Color.Secondary" Value="@GetDouble("sentimentScore")" Class="my-1" />
                <MudText Typo="Typo.body2">@GetDouble("sentimentScore").ToString("F1")/100</MudText>
            </MudItem>
        </MudGrid>
    }
</MudPaper>

@code {
    [Parameter] public Dictionary<string, object>? ReasoningDict { get; set; }

    private string GetVal(string key) => ReasoningDict?.GetValueOrDefault(key)?.ToString() ?? "N/A";

    private double GetDouble(string key)
    {
        if (ReasoningDict?.TryGetValue(key, out var val) == true && val is JsonElement elem)
            return elem.GetDouble();
        return 0;
    }

    private List<string> GetList(string key)
    {
        if (ReasoningDict?.TryGetValue(key, out var val) == true && val is JsonElement elem)
            return elem.EnumerateArray().Select(x => x.GetString() ?? "").ToList();
        return new List<string>();
    }

    private Dictionary<string, string> GetDict(string key)
    {
        if (ReasoningDict?.TryGetValue(key, out var val) == true && val is JsonElement elem)
            return elem.EnumerateObject().ToDictionary(x => x.Name, x => x.Value.ToString());
        return new Dictionary<string, string>();
    }
}
```

---

### Task 2: Enhance ReportDetail Page with Expandable Rows

**Files:**
- Modify: `src/MarketAnalysis.Web/Components/Pages/ReportDetail.razor`

- [ ] **Step 1: Update the `MudDataGrid` to support expansion**
      Add `ShowDetailsButton="true"` and `ChildRowContent` that renders `AnalysisReasoning`.

- [ ] **Step 2: Ensure DTO conversion in `@code` block preserves the `Reasoning` dictionary.**

---

### Task 3: Enhance StockDetail Page with Headlines & Analysis

**Files:**
- Modify: `src/MarketAnalysis.Web/Components/Pages/StockDetail.razor`

- [ ] **Step 1: Add a "Detailed News & Sentiment Feed" section**
      Show the actual headlines and Reddit snippets from the `RecentSentiment` list.

```razor
        <!-- Sentiment Details -->
        <MudItem xs="12">
            <MudCard Elevation="2">
                <MudCardHeader><CardHeaderContent><MudText Typo="Typo.h6">Market Voice & Headlines</MudText></CardHeaderContent></MudCardHeader>
                <MudCardContent>
                    <MudTabs Elevation="0" Outlined="true" Centered="true">
                        @foreach (var s in _detail.RecentSentiment)
                        {
                            <MudTabPanel Text="@s.Source" Icon="@GetSentimentIcon(s.Source)">
                                <MudList T="string" Clickable="false" Dense="true">
                                    @foreach (var head in s.Headlines.Take(15))
                                    {
                                        <MudListItem Icon="@Icons.Material.Filled.Article">
                                            <MudText Typo="Typo.body2">@head</MudText>
                                        </MudListItem>
                                        <MudDivider />
                                    }
                                </MudList>
                            </MudTabPanel>
                        }
                    </MudTabs>
                </MudCardContent>
            </MudCard>
        </MudItem>
```

---

### Task 4: Fix Repository Data Loading

**Files:**
- Modify: `src/MarketAnalysis.Infrastructure/Repositories/ScanReportRepository.cs`

- [ ] **Step 1: Ensure JSONB reasoning is being loaded**
      Postgres JSONB columns should automatically map to `string` or `Dictionary<string, object>` if using `System.Text.Json`.

---

### Task 5: Verification & Testing

- [ ] **Step 1: Run a full scan**
      Trigger a scan and wait for completion.
- [ ] **Step 2: Check ReportDetail**
      Expand a row and verify the "Logic & Analysis" cards are filled correctly.
- [ ] **Step 3: Check StockDetail**
      Verify the "Market Voice" tab shows actual headlines from Finnhub/Reddit.
