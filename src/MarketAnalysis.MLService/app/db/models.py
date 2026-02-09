"""
SQLAlchemy models matching the existing EF Core schema.
Read-only — MLService does not write to these tables.
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, Integer, BigInteger,
    Numeric, String, Text, ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "Stocks"

    Id = Column("Id", Integer, primary_key=True)
    Ticker = Column("Ticker", String(10), unique=True, nullable=False)
    Name = Column("Name", String(200))
    Sector = Column("Sector", String(100))
    Industry = Column("Industry", String(100))
    Exchange = Column("Exchange", String(20))
    MarketCap = Column("MarketCap", Numeric)
    IsActive = Column("IsActive", Boolean, default=True)
    LastUpdatedUtc = Column("LastUpdatedUtc", DateTime)

    price_histories = relationship("PriceHistory", back_populates="stock", lazy="noload")
    technical_signals = relationship("TechnicalSignal", back_populates="stock", lazy="noload")
    fundamental_snapshots = relationship("FundamentalSnapshot", back_populates="stock", lazy="noload")
    sentiment_scores = relationship("SentimentScore", back_populates="stock", lazy="noload")


class PriceHistory(Base):
    __tablename__ = "PriceHistories"

    Id = Column("Id", BigInteger, primary_key=True)
    StockId = Column("StockId", Integer, ForeignKey("Stocks.Id"), nullable=False)
    Date = Column("Date", Date, nullable=False)
    Open = Column("Open", Numeric, nullable=False)
    High = Column("High", Numeric, nullable=False)
    Low = Column("Low", Numeric, nullable=False)
    Close = Column("Close", Numeric, nullable=False)
    AdjClose = Column("AdjClose", Numeric)
    Volume = Column("Volume", BigInteger, nullable=False)

    stock = relationship("Stock", back_populates="price_histories", lazy="noload")


class TechnicalSignal(Base):
    __tablename__ = "TechnicalSignals"

    Id = Column("Id", BigInteger, primary_key=True)
    StockId = Column("StockId", Integer, ForeignKey("Stocks.Id"), nullable=False)
    DetectedDate = Column("DetectedDate", Date, nullable=False)
    PatternType = Column("PatternType", String(50), nullable=False)
    Direction = Column("Direction", String(20), nullable=False)
    Confidence = Column("Confidence", Float, nullable=False)
    StartDate = Column("StartDate", Date)
    EndDate = Column("EndDate", Date)
    Status = Column("Status", String(20))
    KeyPriceLevels = Column("KeyPriceLevels", JSONB)
    Metadata = Column("Metadata", JSONB)

    stock = relationship("Stock", back_populates="technical_signals", lazy="noload")


class FundamentalSnapshot(Base):
    __tablename__ = "FundamentalSnapshots"

    Id = Column("Id", BigInteger, primary_key=True)
    StockId = Column("StockId", Integer, ForeignKey("Stocks.Id"), nullable=False)
    SnapshotDate = Column("SnapshotDate", Date, nullable=False)

    # Financial metrics
    PeRatio = Column("PeRatio", Float)
    ForwardPe = Column("ForwardPe", Float)
    PegRatio = Column("PegRatio", Float)
    PriceToBook = Column("PriceToBook", Float)
    DebtToEquity = Column("DebtToEquity", Float)
    ProfitMargin = Column("ProfitMargin", Float)
    OperatingMargin = Column("OperatingMargin", Float)
    ReturnOnEquity = Column("ReturnOnEquity", Float)
    FreeCashFlow = Column("FreeCashFlow", Float)
    DividendYield = Column("DividendYield", Float)
    Revenue = Column("Revenue", Float)
    RevenueGrowth = Column("RevenueGrowth", Float)
    EarningsGrowth = Column("EarningsGrowth", Float)
    EpsTrailingTwelveMonths = Column("EpsTrailingTwelveMonths", Float)
    MarketCap = Column("MarketCap", Float)
    Beta = Column("Beta", Float)
    FiftyTwoWeekHigh = Column("FiftyTwoWeekHigh", Float)
    FiftyTwoWeekLow = Column("FiftyTwoWeekLow", Float)
    CurrentPrice = Column("CurrentPrice", Float)
    TargetMeanPrice = Column("TargetMeanPrice", Float)

    # Computed scores (0-100)
    ValueScore = Column("ValueScore", Float)
    QualityScore = Column("QualityScore", Float)
    GrowthScore = Column("GrowthScore", Float)
    SafetyScore = Column("SafetyScore", Float)
    CompositeScore = Column("CompositeScore", Float)

    RawData = Column("RawData", JSONB)

    stock = relationship("Stock", back_populates="fundamental_snapshots", lazy="noload")


class SentimentScore(Base):
    __tablename__ = "SentimentScores"

    Id = Column("Id", BigInteger, primary_key=True)
    StockId = Column("StockId", Integer, ForeignKey("Stocks.Id"), nullable=False)
    AnalysisDate = Column("AnalysisDate", Date, nullable=False)
    Source = Column("Source", String(20), nullable=False)
    PositiveScore = Column("PositiveScore", Float, nullable=False)
    NegativeScore = Column("NegativeScore", Float, nullable=False)
    NeutralScore = Column("NeutralScore", Float, nullable=False)
    SampleSize = Column("SampleSize", Integer, nullable=False)
    Headlines = Column("Headlines", JSONB)

    stock = relationship("Stock", back_populates="sentiment_scores", lazy="noload")


class ScanReport(Base):
    __tablename__ = "ScanReports"

    Id = Column("Id", Integer, primary_key=True)
    ReportDate = Column("ReportDate", Date, nullable=False)
    Category = Column("Category", String(20), nullable=False)
    GeneratedAtUtc = Column("GeneratedAtUtc", DateTime, nullable=False)
    ConfigSnapshot = Column("ConfigSnapshot", JSONB)
    TotalStocksScanned = Column("TotalStocksScanned", Integer)
    TotalMatches = Column("TotalMatches", Integer)

    entries = relationship("ScanReportEntry", back_populates="report", lazy="noload")


class ScanReportEntry(Base):
    __tablename__ = "ScanReportEntries"

    Id = Column("Id", BigInteger, primary_key=True)
    ScanReportId = Column("ScanReportId", Integer, ForeignKey("ScanReports.Id"), nullable=False)
    StockId = Column("StockId", Integer, ForeignKey("Stocks.Id"), nullable=False)
    CompositeScore = Column("CompositeScore", Float)
    TechnicalScore = Column("TechnicalScore", Float)
    FundamentalScore = Column("FundamentalScore", Float)
    SentimentScore = Column("SentimentScore", Float)
    Rank = Column("Rank", Integer)
    CurrentPrice = Column("CurrentPrice", Numeric)
    PatternDetected = Column("PatternDetected", String)
    Direction = Column("Direction", String)
    Reasoning = Column("Reasoning", JSONB)

    report = relationship("ScanReport", back_populates="entries", lazy="noload")
