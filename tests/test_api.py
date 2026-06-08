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


def test_data_health_uses_akshare_spot_endpoint(monkeypatch):
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

    monkeypatch.setattr(akshare_client, "_require_akshare", lambda: FakeAkshare())

    client = TestClient(main.app)
    response = client.get("/api/data-health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["data_source"] == "AkShare"
    assert payload["endpoint"] == "stock_zh_a_hist + stock_individual_info_em"
    assert payload["row_count"] == 2
