"""Operational KPI layer over the flight table.

Definitions (DOT-aligned):
- OTP (A14): on-time arrivals (arrival delay < 15 min) / completed
  flights. Cancelled flights are EXCLUDED from both numerator and
  denominator -- this is the single most common OTP bug.
- Completion factor: completed flights / all scheduled flights.
- Cancellation rate: cancelled / all scheduled flights.
- Load factor: passengers / seats, over completed flights only
  (cancelled flights carry 0 passengers and 0 revenue).
- Delay-cause shares: share of delay minutes attributed to each DOT
  cause, over delayed flights (arrival delay >= 15 min) only, so the
  shares sum to 1.0 by construction.
- Route profitability proxy: revenue = passengers x base fare;
  operating-cost proxy = seats x $85 + delay minutes x $35 (delay
  burn: crew, fuel, compensation pressure). It is a ranking proxy,
  not an accounting profit figure -- see README.
"""

from __future__ import annotations

import pandas as pd

ON_TIME_THRESHOLD_MIN = 15
COST_PER_SEAT_USD = 85
COST_PER_DELAY_MIN_USD = 35


def _completed(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df["cancelled"].astype(bool)]


def _arr_delay(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(df["arr_delay_min"], errors="coerce")


def compute_kpis(df: pd.DataFrame) -> dict[str, float]:
    """Headline KPIs for a (possibly filtered) flight table."""
    total = len(df)
    if total == 0:
        return {"otp": 0.0, "completion_factor": 0.0,
                "cancellation_rate": 0.0, "load_factor": 0.0,
                "avg_delay_min_per_flight": 0.0, "flights": 0}
    completed = _completed(df)
    arr = _arr_delay(completed)
    on_time = int((arr < ON_TIME_THRESHOLD_MIN).sum())
    seats = int(completed["seats"].sum())
    passengers = int(completed["passengers"].sum())
    return {
        "otp": on_time / len(completed) if len(completed) else 0.0,
        "completion_factor": len(completed) / total,
        "cancellation_rate": float(df["cancelled"].astype(bool).mean()),
        "load_factor": passengers / seats if seats else 0.0,
        "avg_delay_min_per_flight": float(arr.clip(lower=0).mean())
        if len(completed) else 0.0,
        "flights": total,
    }


def monthly_otp_by_carrier(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly OTP (%) by carrier, completed flights only."""
    completed = _completed(df).copy()
    completed["month"] = pd.to_datetime(completed["flight_date"]).dt.to_period("M")
    completed["on_time"] = _arr_delay(completed) < ON_TIME_THRESHOLD_MIN
    out = (completed.groupby(["month", "carrier_name"])["on_time"]
           .mean().reset_index().rename(columns={"on_time": "otp"}))
    out["otp"] = (out["otp"] * 100).round(1)
    out["month"] = out["month"].astype(str)
    return out


def delay_cause_shares(df: pd.DataFrame,
                       group_col: str | None = None) -> pd.DataFrame:
    """Share of delay minutes by DOT cause, delayed flights only.

    With no group column returns one row per cause summing to 1.0;
    with a group column, shares sum to 1.0 within each group.
    """
    delayed = _completed(df)
    delayed = delayed[_arr_delay(delayed) >= ON_TIME_THRESHOLD_MIN].copy()
    delayed["delay_min"] = _arr_delay(delayed)
    delayed = delayed.dropna(subset=["delay_cause"])
    if group_col is None:
        grouped = (delayed.groupby("delay_cause")["delay_min"]
                   .sum().reset_index())
        grouped["share"] = (grouped["delay_min"]
                            / grouped["delay_min"].sum()).round(4)
        return grouped.sort_values("share", ascending=False)
    grouped = (delayed.groupby([group_col, "delay_cause"])["delay_min"]
               .sum().reset_index())
    totals = grouped.groupby(group_col)["delay_min"].transform("sum")
    grouped["share"] = (grouped["delay_min"] / totals).round(4)
    return grouped.sort_values([group_col, "share"],
                               ascending=[True, False])


def route_profitability(df: pd.DataFrame) -> pd.DataFrame:
    """Per-route economics proxy, ranked by profit proxy descending."""
    completed = _completed(df).copy()
    completed["arr_delay"] = _arr_delay(completed)
    completed["on_time"] = completed["arr_delay"] < ON_TIME_THRESHOLD_MIN
    completed["revenue"] = completed["passengers"] * completed["base_fare_usd"]
    completed["cost"] = (completed["seats"] * COST_PER_SEAT_USD
                         + completed["arr_delay"].clip(lower=0)
                         * COST_PER_DELAY_MIN_USD)
    out = completed.groupby(["route", "origin", "destination"]).agg(
        flights=("flight_id", "count"),
        passengers=("passengers", "sum"),
        seats=("seats", "sum"),
        otp=("on_time", "mean"),
        revenue=("revenue", "sum"),
        cost=("cost", "sum"),
    ).reset_index()
    out["load_factor"] = out["passengers"] / out["seats"]
    out["profit_proxy"] = out["revenue"] - out["cost"]
    out["margin_proxy"] = out["profit_proxy"] / out["revenue"]
    out["otp"] = (out["otp"] * 100).round(1)
    out["load_factor"] = out["load_factor"].round(3)
    return out.sort_values("profit_proxy", ascending=False)


def load_factor_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    """Route x month load factor pivot (completed flights only)."""
    completed = _completed(df).copy()
    completed["month"] = pd.to_datetime(completed["flight_date"]).dt.strftime("%Y-%m")
    piv = completed.pivot_table(index="route", columns="month",
                                values="passengers", aggfunc="sum")
    seats = completed.pivot_table(index="route", columns="month",
                                  values="seats", aggfunc="sum")
    return (piv / seats).round(3)


def monthly_demand(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly passengers and flights (completed flights only)."""
    completed = _completed(df).copy()
    completed["month"] = pd.to_datetime(completed["flight_date"]).dt.strftime("%Y-%m")
    return (completed.groupby("month").agg(
        flights=("flight_id", "count"),
        passengers=("passengers", "sum")).reset_index())
