using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Entities;
using MarketAnalysis.Core.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace MarketAnalysis.Web.Controllers;

[ApiController]
[Route("api/[controller]")]
public class WatchListsController : ControllerBase
{
    private readonly IWatchListRepository _watchListRepo;
    private readonly IStockRepository _stockRepo;

    public WatchListsController(IWatchListRepository watchListRepo, IStockRepository stockRepo)
    {
        _watchListRepo = watchListRepo;
        _stockRepo = stockRepo;
    }

    [HttpGet]
    public async Task<ActionResult<List<WatchListDto>>> GetAll()
    {
        var lists = await _watchListRepo.GetAllWithItemCountAsync();
        return Ok(lists.Select(w => new WatchListDto(
            w.Id, w.Name, w.Description, w.Items.Count, w.CreatedAtUtc)).ToList());
    }

    [HttpGet("{id:int}")]
    public async Task<ActionResult<WatchListDetailDto>> GetById(int id)
    {
        var wl = await _watchListRepo.GetWithItemsAsync(id);
        if (wl is null) return NotFound();

        var items = wl.Items.Select(i => new WatchListItemDto(
            i.Id, i.Stock.Ticker, i.Stock.Name, null, i.AddedAtUtc)).ToList();

        return Ok(new WatchListDetailDto(wl.Id, wl.Name, wl.Description, items));
    }

    [HttpPost]
    public async Task<ActionResult<WatchListDto>> Create([FromBody] CreateWatchListRequest req)
    {
        var wl = new WatchList { Name = req.Name, Description = req.Description };
        await _watchListRepo.AddAsync(wl);
        return CreatedAtAction(nameof(GetById), new { id = wl.Id },
            new WatchListDto(wl.Id, wl.Name, wl.Description, 0, wl.CreatedAtUtc));
    }

    [HttpPost("{id:int}/stocks")]
    public async Task<ActionResult> AddStock(int id, [FromBody] AddStockRequest req)
    {
        var wl = await _watchListRepo.GetWithItemsAsync(id);
        if (wl is null) return NotFound();

        var stock = await _stockRepo.GetOrCreateAsync(req.Ticker);
        if (wl.Items.Any(i => i.StockId == stock.Id))
            return Conflict("Stock already in watchlist");

        wl.Items.Add(new WatchListItem { StockId = stock.Id });
        await _watchListRepo.UpdateAsync(wl);
        return Ok();
    }

    [HttpDelete("{id:int}/stocks/{ticker}")]
    public async Task<ActionResult> RemoveStock(int id, string ticker)
    {
        var wl = await _watchListRepo.GetWithItemsAsync(id);
        if (wl is null) return NotFound();

        var stock = await _stockRepo.GetByTickerAsync(ticker);
        if (stock is null) return NotFound();

        var item = wl.Items.FirstOrDefault(i => i.StockId == stock.Id);
        if (item is null) return NotFound();

        wl.Items.Remove(item);
        await _watchListRepo.UpdateAsync(wl);
        return NoContent();
    }

    [HttpDelete("{id:int}")]
    public async Task<ActionResult> Delete(int id)
    {
        var wl = await _watchListRepo.GetByIdAsync(id);
        if (wl is null) return NotFound();
        await _watchListRepo.DeleteAsync(wl);
        return NoContent();
    }
}

public record CreateWatchListRequest(string Name, string? Description = null);
public record AddStockRequest(string Ticker);
