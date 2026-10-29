"""ETL: seeded flights -> star schema in DuckDB.

Run from the repo root:

    python -m pipeline.etl [--output data/airline_ops.duckdb]

Steps: generate (or read) flights, normalise types, build the four
dimensions, then load fact_flights with surrogate keys. Re-runnable:
existing tables are dropped and rebuilt on every run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_gen.generate import AIRPORTS, CARRIERS, generate_flights  # noqa: E402

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def build_dimensions(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build dim_date / dim_airport / dim_carrier / dim_route."""
    dates = pd.to_datetime(df["flight_date"]).dt
    dim_date = pd.DataFrame({
        "date_key": dates.strftime("%Y%m%d").astype(int),
        "full_date": pd.to_datetime(df["flight_date"]).dt.date,
        "year": dates.year,
        "month": dates.month,
        "month_name": dates.month_name(),
        "quarter": dates.quarter,
        "day_of_week": dates.day_name(),
    }).drop_duplicates("date_key").sort_values("date_key")

    airports = sorted(set(df["origin"]) | set(df["destination"]))
    dim_airport = pd.DataFrame({
        "airport_key": range(1, len(airports) + 1),
        "airport_code": airports,
        "city": [AIRPORTS[a][0] for a in airports],
        "state": [AIRPORTS[a][1] for a in airports],
    })

    carriers = sorted(df["carrier"].unique())
    dim_carrier = pd.DataFrame({
        "carrier_key": range(1, len(carriers) + 1),
        "carrier_code": carriers,
        "carrier_name": [CARRIERS[c] for c in carriers],
    })

    dim_route = (
        df[["route", "origin", "destination",
            "distance_miles", "base_fare_usd"]]
        .drop_duplicates("route").sort_values("route").reset_index(drop=True)
    )
    dim_route.insert(0, "route_key", range(1, len(dim_route) + 1))
    return {
        "dim_date": dim_date,
        "dim_airport": dim_airport,
        "dim_carrier": dim_carrier,
        "dim_route": dim_route,
    }


def build_fact(df: pd.DataFrame, dims: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Attach surrogate keys and shape the fact table."""
    carrier_key = dict(zip(dims["dim_carrier"]["carrier_code"],
                           dims["dim_carrier"]["carrier_key"]))
    route_key = dict(zip(dims["dim_route"]["route"],
                         dims["dim_route"]["route_key"]))
    fact = pd.DataFrame({
        "flight_id": df["flight_id"],
        "date_key": pd.to_datetime(df["flight_date"]).dt.strftime("%Y%m%d").astype(int),
        "carrier_key": df["carrier"].map(carrier_key),
        "route_key": df["route"].map(route_key),
        "origin": df["origin"],
        "destination": df["destination"],
        "aircraft": df["aircraft"],
        "seats": df["seats"].astype(int),
        "passengers": df["passengers"].astype(int),
        "dep_delay_min": pd.to_numeric(df["dep_delay_min"], errors="coerce").astype("Int64"),
        "arr_delay_min": pd.to_numeric(df["arr_delay_min"], errors="coerce").astype("Int64"),
        "delay_cause": df["delay_cause"],
        "cancelled": df["cancelled"].astype(bool),
        "status": df["status"],
    })
    return fact


def load_to_duckdb(df: pd.DataFrame, output: Path) -> dict[str, int]:
    """Build dims + fact and write them to a DuckDB file."""
    import duckdb

    dims = build_dimensions(df)
    fact = build_fact(df, dims)
    output.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(output))
    try:
        con.execute(SCHEMA_PATH.read_text())
        # Fact first: dimensions are referenced by its foreign keys.
        for table in ("fact_flights", "dim_date", "dim_airport",
                      "dim_carrier", "dim_route"):
            con.execute(f"DELETE FROM {table}")
        for name, frame in {**dims, "fact_flights": fact}.items():
            con.register("frame", frame)
            con.execute(f"INSERT INTO {name} SELECT * FROM frame")
            con.unregister("frame")
        counts = {name: len(frame)
                  for name, frame in {**dims, "fact_flights": fact}.items()}
    finally:
        con.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/airline_ops.duckdb")
    args = parser.parse_args()
    df = generate_flights()
    counts = load_to_duckdb(df, Path(args.output))
    print(f"Wrote {args.output}")
    for table, n in counts.items():
        print(f"  {table}: {n:,} rows")


if __name__ == "__main__":
    main()
