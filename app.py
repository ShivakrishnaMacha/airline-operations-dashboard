"""Airline Operations BI dashboard (Streamlit + Plotly).

Panels: KPI row with month-over-month deltas, OTP trend by carrier,
delay-cause breakdown (DOT categories), route profitability table,
load-factor heatmap, seasonal demand chart, flight drilldown table.

Data is generated in-memory from the seeded generator, so the app
runs identically locally and on Streamlit Community Cloud with no
warehouse file required. The DuckDB star schema (pipeline/) is the
warehouse companion for analysts who want SQL access.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_gen.generate import generate_flights  # noqa: E402
from metrics.metrics import (compute_kpis, delay_cause_shares,  # noqa: E402
                             load_factor_heatmap, monthly_demand,
                             monthly_otp_by_carrier, route_profitability)

st.set_page_config(page_title="Airline Operations Dashboard",
                   layout="wide")


@st.cache_data
def load_data() -> pd.DataFrame:
    df = generate_flights()
    df["month"] = pd.to_datetime(df["flight_date"]).dt.strftime("%Y-%m")
    return df


df = load_data()

st.title("✈️ Airline Operations Dashboard")
st.markdown(
    "Seeded synthetic operations for 3 carriers, 8 airports and 30 routes "
    "over 12 months of 2025. On-time = arrival delay under 15 minutes "
    "(DOT A14); cancelled flights are excluded from OTP."
)

# --- Filters -------------------------------------------------------------
carriers = st.sidebar.multiselect(
    "Carrier", sorted(df["carrier_name"].unique()),
    default=sorted(df["carrier_name"].unique()))
airports = st.sidebar.multiselect(
    "Origin airport", sorted(df["origin"].unique()),
    default=sorted(df["origin"].unique()))
filtered = df[df["carrier_name"].isin(carriers)
              & df["origin"].isin(airports)]
if filtered.empty:
    st.warning("No flights match the selected filters.")
    st.stop()

# --- KPI row with prior-month delta --------------------------------------
months = sorted(filtered["month"].unique())
current = filtered[filtered["month"] == months[-1]]
prior = filtered[filtered["month"] == months[-2]] if len(months) > 1 else current
k_now, k_prior = compute_kpis(current), compute_kpis(prior)


def _delta(now: float, before: float) -> str:
    return f"{(now - before) * 100:+.1f} pp vs prior month"


c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("On-time performance (A14)", f"{k_now['otp'] * 100:.1f}%",
          _delta(k_now["otp"], k_prior["otp"]))
c2.metric("Completion factor", f"{k_now['completion_factor'] * 100:.1f}%",
          _delta(k_now["completion_factor"], k_prior["completion_factor"]))
c3.metric("Avg load factor", f"{k_now['load_factor'] * 100:.1f}%",
          _delta(k_now["load_factor"], k_prior["load_factor"]))
c4.metric("Cancellation rate", f"{k_now['cancellation_rate'] * 100:.1f}%",
          _delta(k_now["cancellation_rate"], k_prior["cancellation_rate"]))
c5.metric("Delay min / flight", f"{k_now['avg_delay_min_per_flight']:.1f}",
          f"{k_now['avg_delay_min_per_flight'] - k_prior['avg_delay_min_per_flight']:+.1f} min")

st.caption(f"Latest month in view: {months[-1]} "
           f"({k_now['flights']:,} scheduled flights in that month)")

# --- OTP trend ------------------------------------------------------------
st.subheader("On-time performance trend by carrier")
otp = monthly_otp_by_carrier(filtered)
fig = px.line(otp, x="month", y="otp", color="carrier_name",
              markers=True, labels={"month": "Month", "otp": "OTP (%)",
                                    "carrier_name": "Carrier"})
fig.add_hline(y=80, line_dash="dash",
              annotation_text="80% reference")
st.plotly_chart(fig, use_container_width=True)

# --- Delay causes ---------------------------------------------------------
st.subheader("Delay-cause breakdown (DOT categories)")
cause = delay_cause_shares(filtered)
fig2 = px.bar(cause, x="delay_cause", y="share", color="delay_cause",
              labels={"delay_cause": "Cause", "share": "Share of delay minutes"})
st.plotly_chart(fig2, use_container_width=True)
st.caption("Shares are computed over delayed flights only "
           "(arrival delay ≥ 15 min), so they sum to 1.0.")
by_carrier = delay_cause_shares(filtered, group_col="carrier_name")
st.dataframe(by_carrier, use_container_width=True, hide_index=True)

# --- Route profitability --------------------------------------------------
st.subheader("Route profitability proxy")
routes = route_profitability(filtered)
st.caption("Revenue = passengers × base fare. Cost proxy = seats × $85 "
           "+ delay minutes × $35. A high-profit, low-OTP route is "
           "profitable but unreliable — it shows up here, not hidden.")
st.dataframe(routes, use_container_width=True, hide_index=True)

# --- Load-factor heatmap + seasonal demand --------------------------------
st.subheader("Load factor by route × month")
heat = load_factor_heatmap(filtered)
fig3 = px.imshow(heat, labels={"x": "Month", "y": "Route",
                               "color": "Load factor"},
                 color_continuous_scale="Blues")
st.plotly_chart(fig3, use_container_width=True)

st.subheader("Seasonal demand")
demand = monthly_demand(filtered)
peak = demand.loc[demand["passengers"].idxmax(), "month"]
trough = demand.loc[demand["passengers"].idxmin(), "month"]
fig4 = px.bar(demand, x="month", y="passengers",
              labels={"month": "Month", "passengers": "Passengers"})
st.plotly_chart(fig4, use_container_width=True)
st.caption(f"Peak month: {peak}. Trough month: {trough}.")

# --- Drilldown ------------------------------------------------------------
st.subheader("Flight drilldown")
search = st.text_input("Search route, carrier or flight ID", "")
drill = filtered.copy()
if search:
    mask = (drill["route"].str.contains(search, case=False, na=False)
            | drill["carrier_name"].str.contains(search, case=False, na=False)
            | drill["flight_id"].str.contains(search, case=False, na=False))
    drill = drill[mask]
cols = ["flight_id", "flight_date", "carrier_name", "route",
        "scheduled_dep", "actual_dep", "scheduled_arr", "actual_arr",
        "dep_delay_min", "arr_delay_min", "delay_cause", "status",
        "seats", "passengers"]
st.dataframe(drill[cols].sort_values("flight_date", ascending=False)
             .head(500), use_container_width=True, hide_index=True)
st.caption("Showing up to 500 most recent matching flights.")
