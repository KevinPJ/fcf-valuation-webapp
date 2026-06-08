from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .akshare_client import check_data_source, get_company_snapshot, get_financials
from .dcf import ValuationError, build_sensitivity, calculate_fcff_dcf
from .models import (
    CompanySnapshot,
    FinancialsResponse,
    ForecastRow,
    SensitivityCell,
    ValuationRequest,
    ValuationResponse,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="A股自由现金流估值模型", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "data_source": "AkShare",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/data-health")
def data_health() -> dict[str, object]:
    return check_data_source()


@app.get("/api/company/{symbol}", response_model=CompanySnapshot)
def company(symbol: str) -> CompanySnapshot:
    return get_company_snapshot(symbol)


@app.get("/api/financials/{symbol}", response_model=FinancialsResponse)
def financials(symbol: str) -> FinancialsResponse:
    return get_financials(symbol)


def _latest_value(values: list[float | None], field_name: str, warnings: list[str]) -> float:
    for value in reversed(values):
        if value is not None:
            return value
    raise HTTPException(status_code=422, detail=f"缺少 {field_name}，请提供手动覆盖参数。")


@app.post("/api/valuation", response_model=ValuationResponse)
def valuation(request: ValuationRequest) -> ValuationResponse:
    symbol = request.symbol.strip()
    snapshot = get_company_snapshot(symbol)
    data = get_financials(symbol)
    warnings = [*snapshot.warnings, *data.warnings]

    base_fcf = request.baseFcfOverride
    if base_fcf is None:
        base_fcf = _latest_value([point.free_cash_flow for point in data.periods], "自由现金流", warnings)
    if base_fcf <= 0:
        warnings.append("基准 FCF 为负或为零，DCF 结果对假设高度敏感。")

    if request.netDebtOverride is None:
        cash = _latest_value([point.cash for point in data.periods], "现金", warnings)
        debt = _latest_value([point.debt for point in data.periods], "有息债务", warnings)
        net_debt = debt - cash
    else:
        net_debt = request.netDebtOverride

    shares = request.sharesOverride
    if shares is None:
        shares = _latest_value([point.shares for point in data.periods], "股本", warnings)

    try:
        result = calculate_fcff_dcf(
            base_fcf=base_fcf,
            net_debt=net_debt,
            shares=shares,
            stage1_growth=request.stage1Growth,
            terminal_growth=request.terminalGrowth,
            wacc=request.wacc,
            forecast_years=request.forecastYears,
        )
    except ValuationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    current_price = snapshot.latest_price
    upside = None
    if current_price and current_price > 0:
        upside = result.value_per_share / current_price - 1

    sensitivity = [
        SensitivityCell(**cell)
        for cell in build_sensitivity(
            base_fcf=base_fcf,
            net_debt=net_debt,
            shares=shares,
            stage1_growth=request.stage1Growth,
            terminal_growth=request.terminalGrowth,
            wacc=request.wacc,
            forecast_years=request.forecastYears,
        )
    ]

    return ValuationResponse(
        symbol=symbol,
        status="screen-grade",
        as_of=datetime.now().isoformat(timespec="seconds"),
        base_fcf=result.base_fcf,
        enterprise_value=result.enterprise_value,
        terminal_value=result.terminal_value,
        net_debt=result.net_debt,
        equity_value=result.equity_value,
        shares=result.shares,
        value_per_share=result.value_per_share,
        current_price=current_price,
        upside=upside,
        forecast=[ForecastRow(**row.__dict__) for row in result.forecast],
        sensitivity=sensitivity,
        warnings=warnings,
    )


if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
