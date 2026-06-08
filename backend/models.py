from __future__ import annotations

from pydantic import BaseModel, Field


class FinancialPoint(BaseModel):
    period: str
    revenue: float | None = None
    net_income: float | None = None
    operating_cash_flow: float | None = None
    capital_expenditure: float | None = None
    free_cash_flow: float | None = None
    cash: float | None = None
    debt: float | None = None
    shares: float | None = None


class CompanySnapshot(BaseModel):
    symbol: str
    name: str
    latest_price: float | None = None
    latest_trade_date: str | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    source: str = "AkShare"
    warnings: list[str] = Field(default_factory=list)


class FinancialsResponse(BaseModel):
    symbol: str
    source: str = "AkShare"
    updated_at: str
    periods: list[FinancialPoint]
    warnings: list[str] = Field(default_factory=list)


class ValuationRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    stage1Growth: float = Field(0.08, description="First-stage annual FCF growth, decimal")
    terminalGrowth: float = Field(0.025, description="Terminal growth, decimal")
    wacc: float = Field(0.09, description="Weighted average cost of capital, decimal")
    forecastYears: int = Field(5, ge=1, le=15)
    baseFcfOverride: float | None = Field(None, description="Base FCF in RMB yuan")
    netDebtOverride: float | None = Field(None, description="Net debt in RMB yuan")
    sharesOverride: float | None = Field(None, description="Shares outstanding")


class ForecastRow(BaseModel):
    year: int
    fcf: float
    discount_factor: float
    present_value: float


class SensitivityCell(BaseModel):
    wacc: float
    terminal_growth: float
    value_per_share: float | None


class ValuationResponse(BaseModel):
    symbol: str
    status: str
    as_of: str
    base_fcf: float
    enterprise_value: float
    terminal_value: float
    net_debt: float
    equity_value: float
    shares: float
    value_per_share: float
    current_price: float | None = None
    upside: float | None = None
    forecast: list[ForecastRow]
    sensitivity: list[SensitivityCell]
    warnings: list[str] = Field(default_factory=list)
