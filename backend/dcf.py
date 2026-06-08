from __future__ import annotations

from dataclasses import dataclass


class ValuationError(ValueError):
    """Raised when valuation assumptions are mathematically invalid."""


@dataclass(frozen=True)
class ForecastRowData:
    year: int
    fcf: float
    discount_factor: float
    present_value: float


@dataclass(frozen=True)
class DcfResult:
    base_fcf: float
    enterprise_value: float
    terminal_value: float
    net_debt: float
    equity_value: float
    shares: float
    value_per_share: float
    forecast: list[ForecastRowData]


def calculate_fcff_dcf(
    *,
    base_fcf: float,
    net_debt: float,
    shares: float,
    stage1_growth: float,
    terminal_growth: float,
    wacc: float,
    forecast_years: int = 5,
) -> DcfResult:
    if forecast_years < 1:
        raise ValuationError("forecastYears must be at least 1.")
    if shares <= 0:
        raise ValuationError("Shares outstanding must be positive.")
    if wacc <= terminal_growth:
        raise ValuationError("WACC must be greater than terminal growth.")
    if wacc <= 0:
        raise ValuationError("WACC must be positive.")

    forecast: list[ForecastRowData] = []
    for year in range(1, forecast_years + 1):
        fcf = base_fcf * ((1 + stage1_growth) ** year)
        discount_factor = 1 / ((1 + wacc) ** year)
        present_value = fcf * discount_factor
        forecast.append(
            ForecastRowData(
                year=year,
                fcf=fcf,
                discount_factor=discount_factor,
                present_value=present_value,
            )
        )

    final_year_fcf = forecast[-1].fcf
    terminal_value = final_year_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
    terminal_present_value = terminal_value / ((1 + wacc) ** forecast_years)
    enterprise_value = sum(row.present_value for row in forecast) + terminal_present_value
    equity_value = enterprise_value - net_debt
    value_per_share = equity_value / shares

    return DcfResult(
        base_fcf=base_fcf,
        enterprise_value=enterprise_value,
        terminal_value=terminal_value,
        net_debt=net_debt,
        equity_value=equity_value,
        shares=shares,
        value_per_share=value_per_share,
        forecast=forecast,
    )


def build_sensitivity(
    *,
    base_fcf: float,
    net_debt: float,
    shares: float,
    stage1_growth: float,
    terminal_growth: float,
    wacc: float,
    forecast_years: int,
) -> list[dict[str, float | None]]:
    rows: list[dict[str, float | None]] = []
    for wacc_delta in (-0.01, -0.005, 0, 0.005, 0.01):
        for growth_delta in (-0.005, 0, 0.005):
            cell_wacc = round(wacc + wacc_delta, 4)
            cell_growth = round(terminal_growth + growth_delta, 4)
            try:
                result = calculate_fcff_dcf(
                    base_fcf=base_fcf,
                    net_debt=net_debt,
                    shares=shares,
                    stage1_growth=stage1_growth,
                    terminal_growth=cell_growth,
                    wacc=cell_wacc,
                    forecast_years=forecast_years,
                )
                value = result.value_per_share
            except ValuationError:
                value = None
            rows.append(
                {
                    "wacc": cell_wacc,
                    "terminal_growth": cell_growth,
                    "value_per_share": value,
                }
            )
    return rows
