"""Seeded synthetic flight-operations generator.

Produces ~18,000 flights over 12 months across 8 airports, ~30 routes
and 3 carriers. Deterministic: the same seed always yields the same
dataset, so tests, the dashboard and the warehouse agree exactly.

Delay causes follow the US DOT reporting categories:
carrier, weather, National Aviation System (NAS) and late-arriving
aircraft. A cause is assigned only to flights arriving 15+ minutes
late; on-time and cancelled flights carry no cause.

No downloads, no API keys, no real airline data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 42
N_FLIGHTS = 18_000

AIRPORTS = {
    "ATL": ("Atlanta", "GA"),
    "ORD": ("Chicago", "IL"),
    "DFW": ("Dallas/Fort Worth", "TX"),
    "DEN": ("Denver", "CO"),
    "LAX": ("Los Angeles", "CA"),
    "JFK": ("New York", "NY"),
    "SFO": ("San Francisco", "CA"),
    "MIA": ("Miami", "FL"),
}

CARRIERS = {
    "SL": "Skyline Air",
    "CA": "Coastal Airways",
    "SM": "Summit Airlines",
}

# (origin, destination, distance_miles, base_fare_usd)
ROUTES = [
    ("ATL", "ORD", 606, 148), ("ATL", "DFW", 731, 162), ("ATL", "MIA", 594, 138),
    ("ATL", "LAX", 1946, 268), ("ATL", "JFK", 760, 172), ("ATL", "DEN", 1199, 198),
    ("ORD", "DFW", 802, 168), ("ORD", "DEN", 888, 178), ("ORD", "LAX", 1745, 248),
    ("ORD", "JFK", 719, 158), ("ORD", "SFO", 1846, 258), ("ORD", "MIA", 1197, 198),
    ("DFW", "DEN", 641, 148), ("DFW", "LAX", 1235, 202), ("DFW", "MIA", 1121, 188),
    ("DFW", "SFO", 1464, 218), ("DFW", "JFK", 1391, 212), ("DEN", "LAX", 862, 172),
    ("DEN", "SFO", 967, 182), ("DEN", "JFK", 1625, 238), ("DEN", "MIA", 1727, 248),
    ("LAX", "SFO", 337, 118), ("LAX", "JFK", 2475, 298), ("LAX", "MIA", 2338, 288),
    ("SFO", "JFK", 2586, 308), ("SFO", "MIA", 2594, 308), ("JFK", "MIA", 1090, 188),
    ("ATL", "SFO", 2139, 278), ("MIA", "ATL", 594, 138), ("MIA", "ORD", 1197, 198),
]

AIRCRAFT = {
    "A320": 150,
    "B737": 172,
    "A321": 185,
    "E175": 76,
}

# Per-carrier on-time tendency: higher = more often on time.
CARRIER_OTP_BIAS = {"SL": 0.06, "CA": 0.0, "SM": -0.05}
# Airports with worse-than-average weather/NAS exposure.
AIRPORT_DELAY_BIAS = {"ORD": 6, "JFK": 8, "SFO": 5, "MIA": 4,
                      "ATL": 0, "DFW": 2, "DEN": 3, "LAX": 1}

DELAY_CAUSES = ["carrier", "weather", "NAS", "late_aircraft"]
CAUSE_WEIGHTS = np.array([0.30, 0.20, 0.30, 0.20])


def generate_flights(n: int = N_FLIGHTS, seed: int = SEED) -> pd.DataFrame:
    """Generate the seeded flight-operations table."""
    rng = np.random.default_rng(seed)

    route_idx = rng.integers(0, len(ROUTES), size=n)
    routes = [ROUTES[i] for i in route_idx]
    origins = np.array([r[0] for r in routes])
    destinations = np.array([r[1] for r in routes])
    distances = np.array([r[2] for r in routes], dtype=float)
    fares = np.array([r[3] for r in routes], dtype=float)

    carriers = rng.choice(list(CARRIERS), size=n, p=[0.38, 0.33, 0.29])
    aircraft = rng.choice(list(AIRCRAFT), size=n, p=[0.35, 0.35, 0.18, 0.12])
    seats = np.array([AIRCRAFT[a] for a in aircraft])

    # 12 months of 2025, with a summer + December seasonal peak.
    month_weights = np.array([0.82, 0.78, 0.90, 0.86, 0.95, 1.05,
                              1.12, 1.10, 0.95, 0.92, 0.85, 1.02])
    month_weights = month_weights / month_weights.sum()
    months = rng.choice(np.arange(1, 13), size=n, p=month_weights)
    days = rng.integers(1, 29, size=n)  # 1-28: valid for every month
    dates = pd.Series(pd.to_datetime({"year": 2025, "month": months, "day": days}))

    # Scheduled departure hour: morning/evening banks dominate.
    _hour_p = np.array([0.01, 0.005, 0.005, 0.005, 0.01, 0.03, 0.07, 0.09,
                        0.09, 0.07, 0.06, 0.05, 0.05, 0.05, 0.05, 0.06,
                        0.07, 0.08, 0.06, 0.04, 0.03, 0.02, 0.01, 0.01])
    _hour_p = _hour_p / _hour_p.sum()
    dep_hour = rng.choice(np.arange(24), size=n, p=_hour_p)
    dep_minute = rng.choice([0, 15, 30, 45], size=n)
    sched_dep = dates + pd.to_timedelta(dep_hour * 60 + dep_minute, unit="m")
    # Block time scales with distance (~500 mph + 45 min taxi/turn).
    block_min = (distances / 500 * 60 + 45 + rng.normal(0, 12, size=n)).astype(int)
    sched_arr = sched_dep + pd.to_timedelta(block_min, unit="m")

    cancelled = rng.random(n) < 0.02

    # Departure delay: mostly small, with a long tail. Carrier and
    # airport biases shift the distribution, not the seed.
    carrier_bias = np.array([CARRIER_OTP_BIAS[c] for c in carriers])
    airport_bias = np.array([AIRPORT_DELAY_BIAS[o] for o in origins])
    p_on_time = np.clip(0.72 + carrier_bias, 0.55, 0.85)
    is_late = rng.random(n) > p_on_time
    dep_delay = np.where(
        is_late,
        rng.gamma(shape=2.0, scale=22.0, size=n) + airport_bias,
        rng.normal(0, 5, size=n),
    )
    # Arrival delay tracks departure delay, partly recovered en route.
    arr_delay = dep_delay * rng.uniform(0.7, 1.05, size=n) + rng.normal(0, 6, size=n)
    arr_delay = np.round(arr_delay).astype(int)
    dep_delay = np.round(dep_delay).astype(int)

    # Delay cause, DOT categories, for flights 15+ minutes late only.
    cause = np.full(n, None, dtype=object)
    delayed = (~cancelled) & (arr_delay >= 15)
    cause[delayed] = rng.choice(DELAY_CAUSES, size=int(delayed.sum()),
                                p=CAUSE_WEIGHTS / CAUSE_WEIGHTS.sum())

    # Load factor: seasonal + route variation, clipped to [0.45, 0.98].
    seasonal = 0.06 * np.sin((months - 1) / 12 * 2 * np.pi) + 0.78
    load = np.clip(seasonal + rng.normal(0, 0.09, size=n), 0.45, 0.98)
    passengers = np.floor(seats * load).astype(int)
    passengers = np.minimum(passengers, seats)

    actual_dep = sched_dep + pd.to_timedelta(dep_delay, unit="m")
    actual_arr = sched_arr + pd.to_timedelta(arr_delay, unit="m")

    df = pd.DataFrame({
        "flight_id": [f"{c}{1000 + i}" for i, c in enumerate(carriers)],
        "flight_date": dates.dt.date,
        "carrier": carriers,
        "carrier_name": [CARRIERS[c] for c in carriers],
        "origin": origins,
        "destination": destinations,
        "route": origins + "-" + destinations,
        "distance_miles": distances.astype(int),
        "base_fare_usd": fares.astype(int),
        "aircraft": aircraft,
        "seats": seats,
        "passengers": passengers,
        "scheduled_dep": sched_dep,
        "scheduled_arr": sched_arr,
        "actual_dep": actual_dep,
        "actual_arr": actual_arr,
        "dep_delay_min": dep_delay,
        "arr_delay_min": arr_delay,
        "delay_cause": cause,
        "cancelled": cancelled,
        "status": np.where(cancelled, "Cancelled", "Completed"),
    })
    # Cancelled flights have no actual times and no delay figures.
    df.loc[cancelled, ["actual_dep", "actual_arr",
                       "dep_delay_min", "arr_delay_min"]] = pd.NA
    df.loc[cancelled, "passengers"] = 0
    df.loc[cancelled, "delay_cause"] = None
    return df


if __name__ == "__main__":
    out = generate_flights()
    print(f"{len(out):,} flights, "
          f"{out['cancelled'].mean():.1%} cancelled, "
          f"{out['route'].nunique()} routes, "
          f"{out['origin'].nunique()} airports")
    print(out.head(3).to_string())
