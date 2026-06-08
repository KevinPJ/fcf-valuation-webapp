from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd
import requests
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


def _eastmoney_secid(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    market = "1" if normalized.startswith(("6", "9")) else "0"
    return f"{market}.{normalized}"


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


def _stock_name_from_info(info: dict[str, Any], fallback: str) -> str:
    for key in ("股票简称", "股票名称", "名称"):
        value = info.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return fallback


def _recent_hist(ak: Any, symbol: str) -> pd.DataFrame:
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=45)).strftime("%Y%m%d")
    return ak.stock_zh_a_hist(
        symbol=_normalize_symbol(symbol),
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="",
    )


def _eastmoney_get(url: str, params: dict[str, str], timeout: int = 10) -> dict[str, Any]:
    response = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("data") is None:
        raise ValueError(f"Eastmoney returned empty data: {payload}")
    return payload["data"]


def _eastmoney_quote(symbol: str) -> dict[str, Any]:
    fields = "f43,f57,f58,f86,f116,f117"
    return _eastmoney_get(
        "https://push2.eastmoney.com/api/qt/stock/get",
        {"secid": _eastmoney_secid(symbol), "fields": fields},
    )


def _eastmoney_klines(symbol: str) -> list[str]:
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=45)).strftime("%Y%m%d")
    data = _eastmoney_get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        {
            "secid": _eastmoney_secid(symbol),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "0",
            "beg": start_date,
            "end": end_date,
        },
    )
    klines = data.get("klines") or []
    if not klines:
        raise ValueError("Eastmoney kline endpoint returned no rows.")
    return klines


def _eastmoney_statement(symbol: str, report_name: str) -> list[dict[str, Any]]:
    response = requests.get(
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        params={
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
            "pageSize": "20",
            "pageNumber": "1",
            "reportName": report_name,
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{_normalize_symbol(symbol)}")',
            "source": "WEB",
            "client": "WEB",
        },
        timeout=15,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.eastmoney.com/",
        },
    )
    response.raise_for_status()
    payload = response.json()
    rows = (((payload.get("result") or {}).get("data")) or [])
    if not rows:
        raise ValueError(f"Eastmoney {report_name} returned no rows.")
    return rows


def _period_from_report_date(row: dict[str, Any]) -> str:
    value = str(row.get("REPORT_DATE") or row.get("REPORTDATE") or row.get("REPORT_DATE_NAME") or "")
    return value[:4] if len(value) >= 4 else value


def _eastmoney_financials(symbol: str) -> FinancialsResponse:
    cash_flow = _eastmoney_statement(symbol, "RPT_DMSK_FN_CASHFLOW")
    income = _eastmoney_statement(symbol, "RPT_DMSK_FN_INCOME")
    balance = _eastmoney_statement(symbol, "RPT_DMSK_FN_BALANCE")

    income_by_period = {_period_from_report_date(row): row for row in income}
    balance_by_period = {_period_from_report_date(row): row for row in balance}
    periods: list[FinancialPoint] = []
    for row in cash_flow:
        period = _period_from_report_date(row)
        if not period:
            continue
        inc = income_by_period.get(period, {})
        bal = balance_by_period.get(period, {})
        ocf = _first_value(row, ["NETCASH_OPERATE", "NET_CASH_OPERATE", "NETCASH_OPERATE_A", "CASHFLOW_STATEMENT_NETCASH_OPERATE"])
        capex = _first_value(row, ["CONSTRUCT_LONG_ASSET", "CONSTRUCT_LONG_ASSET_PAY", "PURCHASE_LONG_ASSET", "FIXED_ASSET_OTHER_PAY"])
        if capex is not None and capex > 0:
            capex = -capex
        fcf = ocf + capex if ocf is not None and capex is not None else None
        debt = _sum_values(bal, ["SHORT_LOAN", "NONCURRENT_LIAB_1YEAR", "LONG_LOAN", "BOND_PAYABLE"])
        periods.append(
            FinancialPoint(
                period=period,
                revenue=_first_value(inc, ["TOTAL_OPERATE_INCOME", "OPERATE_INCOME", "TOTAL_INCOME"]),
                net_income=_first_value(inc, ["PARENT_NETPROFIT", "NETPROFIT", "NET_PROFIT"]),
                operating_cash_flow=ocf,
                capital_expenditure=capex,
                free_cash_flow=fcf,
                cash=_first_value(bal, ["MONETARYFUNDS", "CURRENCY_FUNDS", "CASH_DEPOSIT_PBC"]),
                debt=debt,
                shares=_first_value(bal, ["SHARE_CAPITAL", "TOTAL_SHARES", "SHARE_TOTAL", "TOTAL_SHARE_CAPITAL"]),
            )
        )

    periods = sorted({point.period: point for point in periods}.values(), key=lambda item: item.period)[-8:]
    warnings = ["财务报表来自东方财富公开接口。"]
    if not any(point.free_cash_flow is not None for point in periods):
        warnings.append("东方财富字段中未能计算 FCF，可填写基准 FCF 覆盖。")
    if not any(point.shares is not None for point in periods):
        warnings.append("未能取得股本字段，可填写股本覆盖。")

    return FinancialsResponse(
        symbol=_normalize_symbol(symbol),
        source="Eastmoney",
        updated_at=datetime.now().isoformat(timespec="seconds"),
        periods=periods,
        warnings=warnings,
    )


def _yahoo_symbol(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    suffix = "SS" if normalized.startswith(("6", "9")) else "SZ"
    return f"{normalized}.{suffix}"


def _yahoo_chart(symbol: str) -> dict[str, Any]:
    yahoo_symbol = _yahoo_symbol(symbol)
    response = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}",
        params={"range": "1mo", "interval": "1d"},
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    payload = response.json()
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError(f"Yahoo chart returned empty result for {yahoo_symbol}.")
    return result[0]


def _yahoo_company_snapshot(symbol: str) -> CompanySnapshot:
    chart = _yahoo_chart(symbol)
    meta = chart.get("meta") or {}
    timestamps = chart.get("timestamp") or []
    indicators = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
    close_values = indicators.get("close") or []
    latest_price = _safe_float(meta.get("regularMarketPrice"))
    if latest_price is None:
        for value in reversed(close_values):
            latest_price = _safe_float(value)
            if latest_price is not None:
                break
    latest_trade_date = datetime.now().strftime("%Y-%m-%d")
    if timestamps:
        latest_trade_date = datetime.fromtimestamp(timestamps[-1]).strftime("%Y-%m-%d")
    return CompanySnapshot(
        symbol=_normalize_symbol(symbol),
        name=str(meta.get("shortName") or meta.get("symbol") or _normalize_symbol(symbol)),
        latest_price=latest_price,
        latest_trade_date=latest_trade_date,
        market_cap=_safe_float(meta.get("marketCap")),
        source="Yahoo Finance",
        warnings=[],
    )


def check_data_source() -> dict[str, Any]:
    symbol = "000001"
    provider_checks: list[dict[str, Any]] = []
    try:
        quote = _eastmoney_quote(symbol)
        klines = _eastmoney_klines(symbol)
        return {
            "status": "ok",
            "data_source": "Eastmoney",
            "endpoint": "push2 stock/get + push2his kline/get",
            "symbol": symbol,
            "name": str(quote.get("f58") or symbol),
            "row_count": len(klines),
            "sample_columns": ["date", "open", "close", "high", "low", "volume", "amount"],
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "provider_checks": [{"provider": "Eastmoney", "status": "ok"}],
        }
    except Exception as exc:
        provider_checks.append({"provider": "Eastmoney", "status": "failed", "error": str(exc)})

    try:
        chart = _yahoo_chart(symbol)
        timestamps = chart.get("timestamp") or []
        return {
            "status": "ok",
            "data_source": "Yahoo Finance",
            "endpoint": "query1 chart",
            "symbol": _yahoo_symbol(symbol),
            "name": str((chart.get("meta") or {}).get("shortName") or _yahoo_symbol(symbol)),
            "row_count": len(timestamps),
            "sample_columns": ["timestamp", "open", "high", "low", "close", "volume"],
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "provider_checks": [*provider_checks, {"provider": "Yahoo Finance", "status": "ok"}],
        }
    except Exception as exc:
        provider_checks.append({"provider": "Yahoo Finance", "status": "failed", "error": str(exc)})

    ak = _require_akshare()
    try:
        hist = _recent_hist(ak, symbol)
        info = _individual_info_map(ak, symbol)
    except Exception as exc:
        provider_checks.append({"provider": "AkShare", "status": "failed", "error": str(exc)})
        raise _data_error(
            {
                "message": "所有真实财经数据源连通性检查都失败。",
                "provider_checks": provider_checks,
            }
        ) from exc
    if hist is None or hist.empty:
        provider_checks.append({"provider": "AkShare", "status": "failed", "error": "单股票日线接口返回空表。"})
        raise _data_error(
            {
                "message": "所有真实财经数据源连通性检查都失败。",
                "provider_checks": provider_checks,
            }
        )
    return {
        "status": "ok",
        "data_source": "AkShare",
        "endpoint": "stock_zh_a_hist + stock_individual_info_em",
        "symbol": symbol,
        "name": _stock_name_from_info(info, symbol),
        "row_count": int(len(hist)),
        "sample_columns": [str(column) for column in list(hist.columns)[:8]],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "provider_checks": [*provider_checks, {"provider": "AkShare", "status": "ok"}],
    }


@lru_cache(maxsize=128)
def get_company_snapshot(symbol: str) -> CompanySnapshot:
    normalized = _normalize_symbol(symbol)
    ak = _require_akshare()

    warnings: list[str] = []
    try:
        quote = _eastmoney_quote(normalized)
        price = _safe_float(quote.get("f43"))
        if price is not None:
            price = price / 100
        trade_date_raw = str(quote.get("f86") or "")
        latest_trade_date = trade_date_raw[:4] + "-" + trade_date_raw[4:6] + "-" + trade_date_raw[6:8] if len(trade_date_raw) >= 8 else datetime.now().strftime("%Y-%m-%d")
        return CompanySnapshot(
            symbol=normalized,
            name=str(quote.get("f58") or normalized),
            latest_price=price,
            latest_trade_date=latest_trade_date,
            market_cap=_safe_float(quote.get("f116")),
            warnings=warnings,
        )
    except Exception as exc:
        warnings.append(f"东方财富行情兜底失败，改用 AkShare：{exc}")

    try:
        snapshot = _yahoo_company_snapshot(normalized)
        snapshot.warnings = [*warnings, "东方财富行情不可用，当前价格来自 Yahoo Finance。"]
        return snapshot
    except Exception as exc:
        warnings.append(f"Yahoo Finance 行情兜底失败，改用 AkShare：{exc}")

    try:
        info = _individual_info_map(ak, normalized)
        hist = _recent_hist(ak, normalized)
        if hist is None or hist.empty:
            raise _data_error(f"AkShare 日线行情未找到股票代码 {normalized}。", 404)
        row = hist.iloc[-1].to_dict()
        price = _first_value(row, ["收盘", "close", "最新价"])
        market_cap = _first_value(info, ["总市值", "总市值(元)"])
        return CompanySnapshot(
            symbol=normalized,
            name=_stock_name_from_info(info, normalized),
            latest_price=price,
            latest_trade_date=str(row.get("日期", datetime.now().strftime("%Y-%m-%d"))),
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
    eastmoney_error: str | None = None
    try:
        return _eastmoney_financials(normalized)
    except Exception as exc:
        eastmoney_error = str(exc)

    ak = _require_akshare()

    warnings: list[str] = [f"东方财富财报兜底失败，改用 AkShare：{eastmoney_error}"]
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
