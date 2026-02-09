using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace MarketAnalysis.Web.Controllers;

[ApiController]
[Route("api/[controller]")]
public class StocksController : ControllerBase
{
    private readonly IStockRepository _stockRepo;
    private readonly IPriceHistoryRepository _priceRepo;
    private readonly ITechnicalSignalRepository _technicalRepo;
    private readonly IFundamentalRepository _fundamentalRepo;
    private readonly ISentimentRepository _sentimentRepo;

    public StocksController(
        IStockRepository stockRepo, IPriceHistoryRepository priceRepo,
        ITechnicalSignalRepository technicalRepo, IFundamentalRepository fundamentalRepo,
        ISentimentRepository sentimentRepo)
    {
        _stockRepo = stockRepo;
        _priceRepo = priceRepo;
        _technicalRepo = technicalRepo;
        _fundamentalRepo = fundamentalRepo;
        _sentimentRepo = sentimentRepo;
    }

    [HttpGet("search")]
    public async Task<ActionResult<List<object>>> Search([FromQuery] string q, [FromQuery] int max = 20)
    {
        var stocks = await _stockRepo.SearchAsync(q, max);
        return Ok(stocks.Select(s => new { s.Id, s.Ticker, s.Name, s.Sector, s.Exchange }).ToList());
    }

    [HttpGet("{ticker}")]
    public async Task<ActionResult<StockDetailDto>> GetDetail(string ticker)
    {
        var stock = await _stockRepo.GetByTickerAsync(ticker.ToUpperInvariant());
        if (stock is null) return NotFound();

        var prices = await _priceRepo.GetByStockAsync(stock.Id, 180);
        var signals = await _technicalRepo.GetByStockAsync(stock.Id, 30);
        var fundamental = await _fundamentalRepo.GetLatestByStockAsync(stock.Id);
        var sentiment = await _sentimentRepo.GetLatestByStockAsync(stock.Id);

        var priceDtos = prices.OrderBy(p => p.Date)
            .Select(p => new OHLCVBarDto(p.Date, p.Open, p.High, p.Low, p.Close, p.AdjClose, p.Volume))
            .ToList();

        var patternDtos = signals.Select(s => new DetectedPatternDto(
            s.PatternType.ToString(), s.Direction.ToString(), s.Confidence,
            s.StartDate, s.EndDate,
            System.Text.Json.JsonSerializer.Deserialize<Dictionary<string, double>>(s.KeyPriceLevels ?? "{}") ?? new(),
            s.Status, null)).ToList();

        FundamentalDataDto? fundDto = null;
        if (fundamental is not null)
        {
            fundDto = new FundamentalDataDto(
                stock.Ticker, stock.Name, stock.Sector, stock.Industry, stock.Exchange,
                fundamental.PeRatio, fundamental.ForwardPe, fundamental.PegRatio, fundamental.PriceToBook,
                null, null, fundamental.DebtToEquity, fundamental.ProfitMargin, fundamental.OperatingMargin,
                fundamental.ReturnOnEquity, fundamental.FreeCashFlow.HasValue ? (double)fundamental.FreeCashFlow.Value : null,
                fundamental.DividendYield, fundamental.Revenue.HasValue ? (double)fundamental.Revenue.Value : null,
                fundamental.MarketCap.HasValue ? (double)fundamental.MarketCap.Value : null,
                fundamental.Beta, fundamental.FiftyTwoWeekHigh.HasValue ? (double)fundamental.FiftyTwoWeekHigh.Value : null,
                fundamental.FiftyTwoWeekLow.HasValue ? (double)fundamental.FiftyTwoWeekLow.Value : null,
                fundamental.CurrentPrice.HasValue ? (double)fundamental.CurrentPrice.Value : null,
                fundamental.TargetMeanPrice.HasValue ? (double)fundamental.TargetMeanPrice.Value : null,
                fundamental.RecommendationKey);
        }

        var sentDtos = sentiment.Select(s => new TickerSentimentDto(
            stock.Ticker, s.Source.ToString(), s.PositiveScore, s.NegativeScore, s.NeutralScore,
            s.SampleSize, new(), System.Text.Json.JsonSerializer.Deserialize<List<string>>(s.Headlines ?? "[]") ?? new())).ToList();

        return Ok(new StockDetailDto(
            stock.Id, stock.Ticker, stock.Name, stock.Sector, stock.Industry, stock.Exchange,
            stock.MarketCap, prices.FirstOrDefault()?.Close, priceDtos, patternDtos, fundDto, sentDtos));
    }
}
