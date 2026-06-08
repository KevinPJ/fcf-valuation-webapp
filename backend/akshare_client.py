from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

import pandas as pd
from fastapi import HTTPException

from .models import CompanySnapshot, FinancialPoint, FinancialsResponse


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        text = str(value).replace(",", "").replace("--", "").strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _first_value(row: dict[str, Any], candidates: list[str]) -> float | None:
    for key in candidates:
        if key in row:
            value = _safe_float(row[key])
            if value is not None:
                return value
    return None


def _sum_values(row: dict[str, Any], candidates: list[str]) -> float | None:
    values = [_safe_float(row.get(key)) for key in candidates if key in row]
    clean_values = [value for value in values if value is not None]
    if not clean_values:
        return None
    return sum(clean_values)


def _import_akshare():
    try:
        import akshare as ak  # type: ignore

        return ak
    except Exception:
        return None


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".SZ", "").replace(".SH", "")


def _sina_symbol(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    if normalized.startswith(("6", "9")):
        return f"sh{normalized}"
    return f"sz{normalized}"


def _data_error(message: str, status_code: int = 502) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


def _require_akshare():
    ak = _import_akshare()
    if ak is None:
        raise _data_error("后端未安装 akshare，无法获取真实财经数据。请先安装 requirements.txt。", 503)
    return ak


def _individual_info_map(ak: Any, symbol: str) -> dict[str, Any]:
    try:
        info = ak.stock_individual_info_em(symbol=symbol)
    except Exception:
        return {}
    if info is None or info.empty:
        return {}
    columns = list(info.columns)
    if len(columns) < 2:
        return {}
    return {str(row[columns[0]]): row[columns[1]] for row in info.to_dict("records")}


def _share_count_from_info(info: dict[str, Any]) -> float | None:
    return _first_value(info, ["总股本", "流通股", "总股本(股)", "流通股本"])


def check_data_source() -> dict[str, Any]:
    ak = _require_akshare()
    try:
        spot = ak.stock_zh_a_spot_em()
    except Exception as exc:
        raise _data_error(f"AkShare 数据源连通性检查失败：{exc}") from exc
    if spot is None or spot.empty:
        raise _data_error("AkShare 数据源连通性检查失败：行情接口返回空表。")
    return {
        "status": "ok",
        "data_source": "AkShare",
        "endpoint": "stock_zh_a_spot_em",
        "row_count": int(len(spot)),
        "sample_columns": [str(column) for column in list(spot.columns)[:8]],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


@lru_cache(maxsize=128)
def get_company_snapshot(symbol: str) -> CompanySnapshot:
    normalized = _normalize_symbol(symbol)
    ak = _require_akshare()

    warnings: list[str] = []
    try:
        spot = ak.stock_zh_a_spot_em()
        code_col = "代码"
        row_df = spot[spot[code_col].astype(str) == normalized]
        if row_df.empty:
            raise _data_error(f"AkShare 实时行情未找到股票代码 {normalized}。", 404)
        row = row_df.iloc[0].to_dict()
        price = _safe_float(row.get("最新价"))
        market_cap = _safe_float(row.get("总市值"))
        return CompanySnapshot(
            symbol=normalized,
            name=str(row.get("名称", normalized)),
            latest_price=price,
            latest_trade_date=datetime.now().strftime("%Y-%m-%d"),
            market_cap=market_cap,
            warnings=warnings,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _data_error(f"AkShare 行情获取失败：{exc}") from exc


@lru_cache(maxsize=128)
def get_financials(symbol: str) -> FinancialsResponse:
    normalized = _normalize_symbol(symbol)
    prefixed = _sina_symbol(normalized)
    ak = _require_akshare()

    warnings: list[str] = []
    try:
        cash_flow = ak.stock_financial_report_sina(stock=prefixed, symbol="现金流量表")
        balance = ak.stock_financial_report_sina(stock=prefixed, symbol="资产负债表")
        income = ak.stock_financial_report_sina(stock=prefixed, symbol="利润表")
    except Exception as exc:
        raise _data_error(f"AkShare 财务报表获取失败：{exc}") from exc

    if cash_flow.empty:
        raise _data_error(f"AkShare 未返回 {normalized} 的现金流量表。", 404)

    def period_key(value: Any) -> str:
        text = str(value)
        return text[:4] if len(text) >= 4 else text

    cash_flow = cash_flow.copy()
    date_col = "报告日" if "报告日" in cash_flow.columns else cash_flow.columns[0]
    cash_flow["_period"] = cash_flow[date_col].map(period_key)

    balance_by_period = {}
    if not balance.empty:
        bal_date_col = "报告日" if "报告日" in balance.columns else balance.columns[0]
        balance = balance.copy()
        balance["_period"] = balance[bal_date_col].map(period_key)
        balance_by_period = {row["_period"]: row for row in balance.to_dict("records")}

    income_by_period = {}
    if not income.empty:
        inc_date_col = "报告日" if "报告日" in income.columns else income.columns[0]
        income = income.copy()
        income["_period"] = income[inc_date_col].map(period_key)
        income_by_period = {row["_period"]: row for row in income.to_dict("records")}

    periods: list[FinancialPoint] = []
    for row in cash_flow.to_dict("records"):
        period = row["_period"]
        bal = balance_by_period.get(period, {})
        inc = income_by_period.get(period, {})
        ocf = _first_value(row, ["经营活动产生的现金流量净额", "经营活动现金流量净额"])
        capex = _first_value(row, ["购建固定资产、无形资产和其他长期资产支付的现金", "购建固定资产无形资产和其他长期资产支付的现金"])
        if capex is not None and capex > 0:
            capex = -capex
        fcf = ocf + capex if ocf is not None and capex is not None else None
        point = FinancialPoint(
            period=period,
            revenue=_first_value(inc, ["营业总收入", "营业收入"]),
            net_income=_first_value(inc, ["净利润", "归属于母公司所有者的净利润"]),
            operating_cash_flow=ocf,
            capital_expenditure=capex,
            free_cash_flow=fcf,
            cash=_first_value(bal, ["货币资金", "现金及存放中央银行款项"]),
            debt=_sum_values(bal, ["短期借款", "一年内到期的非流动负债", "长期借款", "应付债券"]),
            shares=_first_value(bal, ["实收资本（或股本）", "股本"]),
        )
        periods.append(point)

    periods = sorted(periods, key=lambda item: item.period)[-8:]
    if not any(point.shares is not None for point in periods):
        share_count = _share_count_from_info(_individual_info_map(ak, normalized))
        if share_count is not None:
            for point in periods:
                point.shares = share_count

    if not any(point.free_cash_flow is not None for point in periods):
        warnings.append("未能从 AkShare 字段中计算 FCF，可在估值请求中手动覆盖 baseFcfOverride。")
    if not any(point.shares is not None for point in periods):
        warnings.append("未能取得股本字段，可在估值请求中手动覆盖 sharesOverride。")

    return FinancialsResponse(
        symbol=normalized,
        updated_at=datetime.now().isoformat(timespec="seconds"),
        periods=periods,
        warnings=warnings,
    )
