using MarketAnalysis.Core.Entities;

namespace MarketAnalysis.Core.Interfaces;

public interface IRepository<T> where T : class
{
    Task<T?> GetByIdAsync(int id);
    Task<List<T>> GetAllAsync();
    Task<T> AddAsync(T entity);
    Task AddRangeAsync(IEnumerable<T> entities);
    Task UpdateAsync(T entity);
    Task DeleteAsync(T entity);
    Task SaveChangesAsync();
}

public interface IStockRepository : IRepository<Stock>
{
    Task<Stock?> GetByTickerAsync(string ticker);
    Task<List<Stock>> GetByTickersAsync(IEnumerable<string> tickers);
    Task<Stock> GetOrCreateAsync(string ticker, string? name = null);
    Task<List<Stock>> SearchAsync(string query, int maxResults = 20);
}

public interface IPriceHistoryRepository : IRepository<PriceHistory>
{
    Task<List<PriceHistory>> GetByStockAsync(int stockId, int days = 365);
    Task<List<PriceHistory>> GetByStockAndDateRangeAsync(int stockId, DateOnly from, DateOnly to);
    Task<PriceHistory?> GetLatestAsync(int stockId);
    Task UpsertRangeAsync(int stockId, IEnumerable<PriceHistory> prices);
}

public interface ITechnicalSignalRepository : IRepository<TechnicalSignal>
{
    Task<List<TechnicalSignal>> GetByStockAsync(int stockId, int days = 30);
    Task<List<TechnicalSignal>> GetByDateAsync(DateOnly date);
    Task<List<TechnicalSignal>> GetRecentByStockAsync(int stockId, int limit = 10);
    Task<List<TechnicalSignal>> GetAllRecentAsync(int days = 7);
}

public interface IFundamentalRepository : IRepository<FundamentalSnapshot>
{
    Task<FundamentalSnapshot?> GetLatestByStockAsync(int stockId);
    Task<List<FundamentalSnapshot>> GetByStockAsync(int stockId, int limit = 10);
}

public interface ISentimentRepository : IRepository<SentimentScore>
{
    Task<List<SentimentScore>> GetByStockAsync(int stockId, int days = 30);
    Task<List<SentimentScore>> GetByStockAndDateAsync(int stockId, DateOnly date);
    Task<List<SentimentScore>> GetLatestByStockAsync(int stockId);
}

public interface IScanReportRepository : IRepository<ScanReport>
{
    Task<List<ScanReport>> GetByDateAsync(DateOnly date);
    Task<ScanReport?> GetLatestByCategoryAsync(Enums.ReportCategory category);
    Task<List<ScanReport>> GetRecentAsync(int limit = 20);
    Task<ScanReport?> GetWithEntriesAsync(int reportId);
}

public interface IWatchListRepository : IRepository<WatchList>
{
    Task<WatchList?> GetWithItemsAsync(int watchListId);
    Task<List<WatchList>> GetAllWithItemCountAsync();
}

public interface IUserScanConfigRepository : IRepository<UserScanConfig>
{
    Task<UserScanConfig?> GetDefaultAsync();
    Task SetDefaultAsync(int configId);
}

public interface IIndexDefinitionRepository : IRepository<IndexDefinition>
{
    Task<List<IndexDefinition>> GetEnabledAsync();
    Task<IndexDefinition?> GetByNameAsync(string name);
}
