using MarketAnalysis.Core.DTOs;
using MarketAnalysis.Core.Enums;
using MarketAnalysis.Core.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace MarketAnalysis.Web.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ConfigController : ControllerBase
{
    private readonly IUserScanConfigRepository _configRepo;

    public ConfigController(IUserScanConfigRepository configRepo)
    {
        _configRepo = configRepo;
    }

    [HttpGet]
    public async Task<ActionResult<List<UserScanConfigDto>>> GetAll()
    {
        var configs = await _configRepo.GetAllAsync();
        return Ok(configs.Select(MapToDto).ToList());
    }

    [HttpGet("default")]
    public async Task<ActionResult<UserScanConfigDto>> GetDefault()
    {
        var config = await _configRepo.GetDefaultAsync();
        if (config is null) return NotFound();
        return Ok(MapToDto(config));
    }

    [HttpGet("{id:int}")]
    public async Task<ActionResult<UserScanConfigDto>> GetById(int id)
    {
        var config = await _configRepo.GetByIdAsync(id);
        if (config is null) return NotFound();
        return Ok(MapToDto(config));
    }

    [HttpPut("{id:int}")]
    public async Task<ActionResult> Update(int id, [FromBody] UserScanConfigDto dto)
    {
        var config = await _configRepo.GetByIdAsync(id);
        if (config is null) return NotFound();

        config.Name = dto.Name;
        config.EnabledPatterns = dto.EnabledPatterns.ToArray();
        config.PriceRangeMin = dto.PriceRangeMin;
        config.PriceRangeMax = dto.PriceRangeMax;
        config.MinMarketCap = dto.MinMarketCap;
        config.MaxPERatio = dto.MaxPERatio;
        config.MaxDebtToEquity = dto.MaxDebtToEquity;
        config.MinProfitMargin = dto.MinProfitMargin;
        config.MinSentimentScore = dto.MinSentimentScore;
        config.MinSentimentSampleSize = dto.MinSentimentSampleSize;
        config.TechnicalWeight = dto.TechnicalWeight;
        config.FundamentalWeight = dto.FundamentalWeight;
        config.SentimentWeight = dto.SentimentWeight;
        config.EnabledCategories = dto.EnabledCategories.ToArray();
        config.EnabledSentimentSources = dto.EnabledSentimentSources.ToArray();
        config.EnabledIndicators = dto.EnabledIndicators.ToArray();
        config.UpdatedAtUtc = DateTime.UtcNow;

        await _configRepo.UpdateAsync(config);
        return Ok(MapToDto(config));
    }

    [HttpPost("{id:int}/set-default")]
    public async Task<ActionResult> SetDefault(int id)
    {
        var config = await _configRepo.GetByIdAsync(id);
        if (config is null) return NotFound();
        await _configRepo.SetDefaultAsync(id);
        return Ok();
    }

    private static UserScanConfigDto MapToDto(Core.Entities.UserScanConfig c) => new(
        c.Id, c.Name, c.IsDefault,
        c.EnabledPatterns.ToList(),
        c.PriceRangeMin, c.PriceRangeMax, c.MinMarketCap,
        c.MaxPERatio, c.MaxDebtToEquity, c.MinProfitMargin, c.MinSentimentScore,
        c.MinSentimentSampleSize,
        c.TechnicalWeight, c.FundamentalWeight, c.SentimentWeight,
        c.EnabledCategories.ToList(),
        c.EnabledSentimentSources.ToList(),
        c.EnabledIndicators.ToList());
}
