"""Tests for the airline operations KPI layer.

Every test runs against the same seeded dataset (seed 42) the
dashboard uses, so a passing suite means the shipped numbers are
the tested numbers.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_gen.generate import generate_flights  # noqa: E402
from metrics.metrics import (compute_kpis, delay_cause_shares,  # noqa: E402
                             load_factor_heatmap, monthly_demand,
                             route_profitability)


@pytest.fixture(scope="module")
def df():
    return generate_flights()


def test_dataset_shape(df):
    assert len(df) == 18_000
    assert df["route"].nunique() == 30
    assert df["origin"].nunique() == 8
    assert df["carrier"].nunique() == 3


def test_otp_arithmetic_excludes_cancelled(df):
    """OTP == on-time / completed, exactly; cancelled excluded."""
    kpis = compute_kpis(df)
    completed = df[~df["cancelled"].astype(bool)]
    arr = pd.to_numeric(completed["arr_delay_min"], errors="coerce")
    expected = float(((arr < 15).sum()) / len(completed))
    assert kpis["otp"] == pytest.approx(expected, abs=1e-12)
    # And it must differ from the naive all-flights computation when
    # cancellations exist (i.e. the exclusion actually matters).
    assert df["cancelled"].sum() > 0
    naive = float(((pd.to_numeric(df["arr_delay_min"], errors="coerce") < 15)
                   .fillna(False).sum()) / len(df))
    assert kpis["otp"] != pytest.approx(naive, abs=1e-6)


def test_cancelled_flights_have_no_delays_or_passengers(df):
    cancelled = df[df["cancelled"].astype(bool)]
    assert len(cancelled) > 0
    assert cancelled["passengers"].eq(0).all()
    assert pd.to_numeric(cancelled["arr_delay_min"],
                         errors="coerce").isna().all()
    assert cancelled["delay_cause"].isna().all()


def test_load_factor_in_unit_interval(df):
    kpis = compute_kpis(df)
    assert 0.0 <= kpis["load_factor"] <= 1.0
    routes = route_profitability(df)
    assert routes["load_factor"].between(0, 1).all()
    heat = load_factor_heatmap(df)
    assert ((heat >= 0) & (heat <= 1) | heat.isna()).all().all()


def test_passengers_never_exceed_seats(df):
    assert (df["passengers"] <= df["seats"]).all()
    assert (df["passengers"] >= 0).all()
    assert (df["seats"] > 0).all()


def test_delay_cause_shares_sum_to_one(df):
    shares = delay_cause_shares(df)
    assert shares["share"].sum() == pytest.approx(1.0, abs=1e-3)
    assert set(shares["delay_cause"]) <= {
        "carrier", "weather", "NAS", "late_aircraft"}
    by_carrier = delay_cause_shares(df, group_col="carrier_name")
    for _, group in by_carrier.groupby("carrier_name"):
        assert group["share"].sum() == pytest.approx(1.0, abs=1e-3)


def test_completion_plus_cancellation_equals_one(df):
    kpis = compute_kpis(df)
    assert kpis["completion_factor"] + kpis["cancellation_rate"] == pytest.approx(1.0)
    assert 0.0 < kpis["cancellation_rate"] < 0.10


def test_route_profitability_columns_and_ranking(df):
    routes = route_profitability(df)
    assert len(routes) == 30
    for col in ("flights", "passengers", "seats", "otp",
                "revenue", "cost", "profit_proxy", "margin_proxy"):
        assert col in routes.columns
    assert routes["profit_proxy"].is_monotonic_decreasing
    assert (routes["revenue"] > routes["cost"]).any()


def test_monthly_demand_covers_twelve_months(df):
    demand = monthly_demand(df)
    assert len(demand) == 12
    assert demand["flights"].sum() == int((~df["cancelled"].astype(bool)).sum())
    assert demand["passengers"].sum() == int(
        df.loc[~df["cancelled"].astype(bool), "passengers"].sum())
