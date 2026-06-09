from fastapi.testclient import TestClient
import pandas as pd

from backend import main
import backend.akshare_client as akshare_client
from backend.akshare_client import _sina_symbol
from backend.models import CompanySnapshot, FinancialPoint, FinancialsResponse


def test_sina_symbol_adds_market_prefix():
    assert _sina_symbol("600000") == "sh600000"
    assert _sina_symbol("000001") == "sz000001"
    assert _sina_symbol("300750.SZ") == "sz300750"


def test_api_returns_company_financials_and_valuation(monkeypatch):
    company = CompanySnapshot(
        symbol="000001",
        name="平安银行",
        latest_price=10,
        latest_trade_date="2026-06-07",
    )
    financials = FinancialsResponse(
        symbol="000001",
        updated_at="2026-06-07T00:00:00",
        periods=[
            FinancialPoint(
                period="2024",
                revenue=1000,
                net_income=100,
                operating_cash_flow=160,
                capital_expenditure=-40,
                free_cash_flow=120,
                cash=300,
                debt=500,
                shares=10,
            )
        ],
    )

    monkeypatch.setattr(main, "get_company_snapshot", lambda symbol: company)
    monkeypatch.setattr(main, "get_financials", lambda symbol: financials)

    client = TestClient(main.app)

    assert client.get("/api/company/000001").json()["name"] == "平安银行"
    assert client.get("/api/financials/000001").json()["periods"][0]["free_cash_flow"] == 120

    response = client.post(
        "/api/valuation",
        json={
            "symbol": "000001",
            "stage1Growth": 0.05,
            "terminalGrowth": 0.02,
            "wacc": 0.1,
            "forecastYears": 5,
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "screen-grade"
    assert payload["value_per_share"] > 0
    assert len(payload["forecast"]) == 5
    assert len(payload["sensitivity"]) == 15


def test_valuation_resolves_missing_model_inputs(monkeypatch):
    company = CompanySnapshot(
        symbol="600519",
        name="贵州茅台",
        latest_price=1500,
        latest_trade_date="2026-06-08",
        market_cap=1_884_000_000_000,
        shares_outstanding=1_256_000_000,
        source="Eastmoney",
    )
    financials = FinancialsResponse(
        symbol="600519",
        updated_at="2026-06-08T00:00:00",
        periods=[
            FinancialPoint(
                period="2024",
                revenue=170_000_000_000,
                net_income=86_000_000_000,
                operating_cash_flow=91_000_000_000,
                capital_expenditure=None,
                free_cash_flow=None,
                cash=None,
                debt=None,
                shares=None,
            )
        ],
    )

    monkeypatch.setattr(main, "get_company_snapshot", lambda symbol: company)
    monkeypatch.setattr(main, "get_financials", lambda symbol: financials)

    client = TestClient(main.app)
    response = client.post(
        "/api/valuation",
        json={
            "symbol": "600519",
            "stage1Growth": 0.08,
            "terminalGrowth": 0.025,
            "wacc": 0.09,
            "forecastYears": 5,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["base_fcf"] == 91_000_000_000
    assert payload["net_debt"] == 0
    assert payload["shares"] == 1_256_000_000
    assert payload["value_per_share"] > 0
    assert any("经营现金流代理" in warning for warning in payload["warnings"])
    assert any("有息债务" in warning for warning in payload["warnings"])


def test_valuation_uses_net_income_when_cash_flow_is_missing(monkeypatch):
    company = CompanySnapshot(
        symbol="600519",
        name="贵州茅台",
        latest_price=1500,
        latest_trade_date="2026-06-08",
        market_cap=1_884_000_000_000,
    )
    financials = FinancialsResponse(
        symbol="600519",
        updated_at="2026-06-08T00:00:00",
        periods=[
            FinancialPoint(
                period="2024",
                revenue=170_000_000_000,
                net_income=86_000_000_000,
                operating_cash_flow=None,
                capital_expenditure=None,
                free_cash_flow=None,
                cash=None,
                debt=None,
                shares=None,
            )
        ],
    )

    monkeypatch.setattr(main, "get_company_snapshot", lambda symbol: company)
    monkeypatch.setattr(main, "get_financials", lambda symbol: financials)

    client = TestClient(main.app)
    response = client.post(
        "/api/valuation",
        json={
            "symbol": "600519",
            "stage1Growth": 0.08,
            "terminalGrowth": 0.025,
            "wacc": 0.09,
            "forecastYears": 5,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["base_fcf"] == 86_000_000_000
    assert payload["shares"] == 1_256_000_000
    assert any("净利润代理" in warning for warning in payload["warnings"])
    assert any("市值 / 最新价格" in warning for warning in payload["warnings"])


def test_data_health_prefers_eastmoney_direct(monkeypatch):
    monkeypatch.setattr(
        akshare_client,
        "_eastmoney_quote",
        lambda symbol: {"f58": "平安银行"},
    )
    monkeypatch.setattr(
        akshare_client,
        "_eastmoney_klines",
        lambda symbol: ["2026-06-05,10,10.1,10.2,9.9,1,1", "2026-06-08,10.1,10.2,10.3,10.0,1,1"],
    )

    client = TestClient(main.app)
    response = client.get("/api/data-health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["data_source"] == "Eastmoney"
    assert payload["endpoint"] == "push2 stock/get + push2his kline/get"
    assert payload["row_count"] == 2


def test_data_health_uses_yahoo_when_eastmoney_fails(monkeypatch):
    monkeypatch.setattr(
        akshare_client,
        "_eastmoney_quote",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("eastmoney down")),
    )
    monkeypatch.setattr(
        akshare_client,
        "_yahoo_chart",
        lambda symbol: {
            "meta": {"shortName": "Ping An Bank", "symbol": "000001.SZ"},
            "timestamp": [1780848000, 1780934400],
            "indicators": {"quote": [{"close": [10.0, 10.2]}]},
        },
    )

    client = TestClient(main.app)
    response = client.get("/api/data-health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["data_source"] == "Yahoo Finance"
    assert payload["symbol"] == "000001.SZ"
    assert payload["row_count"] == 2
    assert payload["provider_checks"][0]["provider"] == "Eastmoney"
    assert payload["provider_checks"][0]["status"] == "failed"
    assert payload["provider_checks"][1]["provider"] == "Yahoo Finance"
    assert payload["provider_checks"][1]["status"] == "ok"


def test_data_health_falls_back_to_akshare(monkeypatch):
    class FakeAkshare:
        def stock_zh_a_hist(self, symbol, period, start_date, end_date, adjust):
            return pd.DataFrame(
                [
                    {"日期": "2026-06-05", "收盘": 10.0},
                    {"日期": "2026-06-08", "收盘": 10.2},
                ]
            )

        def stock_individual_info_em(self, symbol):
            return pd.DataFrame(
                [
                    {"item": "股票简称", "value": "平安银行"},
                    {"item": "总股本", "value": 19405900000},
                ]
            )

    monkeypatch.setattr(
        akshare_client,
        "_eastmoney_quote",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("eastmoney down")),
    )
    monkeypatch.setattr(
        akshare_client,
        "_yahoo_chart",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("yahoo down")),
    )
    monkeypatch.setattr(akshare_client, "_require_akshare", lambda: FakeAkshare())

    client = TestClient(main.app)
    response = client.get("/api/data-health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["data_source"] == "AkShare"
    assert payload["endpoint"] == "stock_zh_a_hist + stock_individual_info_em"
    assert payload["row_count"] == 2


def test_data_health_reports_all_provider_errors(monkeypatch):
    class FakeAkshare:
        def stock_zh_a_hist(self, symbol, period, start_date, end_date, adjust):
            raise RuntimeError("akshare down")

    monkeypatch.setattr(
        akshare_client,
        "_eastmoney_quote",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("eastmoney down")),
    )
    monkeypatch.setattr(
        akshare_client,
        "_yahoo_chart",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("yahoo down")),
    )
    monkeypatch.setattr(akshare_client, "_require_akshare", lambda: FakeAkshare())

    client = TestClient(main.app)
    response = client.get("/api/data-health")
    payload = response.json()

    assert response.status_code == 502
    assert payload["detail"]["message"] == "所有真实财经数据源连通性检查都失败。"
    assert [item["provider"] for item in payload["detail"]["provider_checks"]] == [
        "Eastmoney",
        "Yahoo Finance",
        "AkShare",
    ]
