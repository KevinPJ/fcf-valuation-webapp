import pytest

from backend.dcf import ValuationError, build_sensitivity, calculate_fcff_dcf


def test_fcff_dcf_math_and_bridge():
    result = calculate_fcff_dcf(
        base_fcf=100,
        net_debt=20,
        shares=10,
        stage1_growth=0.05,
        terminal_growth=0.02,
        wacc=0.10,
        forecast_years=5,
    )

    assert len(result.forecast) == 5
    assert result.enterprise_value > 0
    assert result.equity_value == pytest.approx(result.enterprise_value - 20)
    assert result.value_per_share == pytest.approx(result.equity_value / 10)


def test_rejects_wacc_less_than_terminal_growth():
    with pytest.raises(ValuationError):
        calculate_fcff_dcf(
            base_fcf=100,
            net_debt=0,
            shares=10,
            stage1_growth=0.05,
            terminal_growth=0.04,
            wacc=0.04,
            forecast_years=5,
        )


def test_negative_fcf_is_allowed_but_calculated():
    result = calculate_fcff_dcf(
        base_fcf=-100,
        net_debt=20,
        shares=10,
        stage1_growth=0.03,
        terminal_growth=0.01,
        wacc=0.09,
        forecast_years=5,
    )

    assert result.value_per_share < 0


def test_sensitivity_handles_invalid_cells():
    rows = build_sensitivity(
        base_fcf=100,
        net_debt=0,
        shares=10,
        stage1_growth=0.05,
        terminal_growth=0.095,
        wacc=0.10,
        forecast_years=5,
    )

    assert len(rows) == 15
    assert any(row["value_per_share"] is None for row in rows)
