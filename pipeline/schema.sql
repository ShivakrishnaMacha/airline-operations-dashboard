-- Airline operations star schema (DuckDB).
--
-- dbt-model mapping (documented, not executed here):
--   dim_date     <- staging: distinct flight_date, calendar attributes
--   dim_airport  <- staging: distinct airport codes + city/state lookup
--   dim_carrier  <- staging: distinct carrier codes + names
--   dim_route    <- staging: distinct origin/destination pairs + distance
--   fact_flights <- staging: one row per flight, surrogate keys to dims
--
-- Grain: one row per flight in fact_flights. Cancelled flights are
-- kept in the fact (status = 'Cancelled', passengers = 0, delay NULL)
-- so completion factor and cancellation rate are computable from the
-- same table; OTP explicitly excludes them (see metrics/metrics.py).

CREATE TABLE IF NOT EXISTS dim_date (
    date_key        INTEGER PRIMARY KEY,
    full_date       DATE    NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    month_name      VARCHAR NOT NULL,
    quarter         INTEGER NOT NULL,
    day_of_week     VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_airport (
    airport_key     INTEGER PRIMARY KEY,
    airport_code    VARCHAR NOT NULL UNIQUE,
    city            VARCHAR NOT NULL,
    state           VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_carrier (
    carrier_key     INTEGER PRIMARY KEY,
    carrier_code    VARCHAR NOT NULL UNIQUE,
    carrier_name    VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_route (
    route_key       INTEGER PRIMARY KEY,
    route           VARCHAR NOT NULL UNIQUE,
    origin          VARCHAR NOT NULL,
    destination     VARCHAR NOT NULL,
    distance_miles  INTEGER NOT NULL,
    base_fare_usd   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_flights (
    flight_id       VARCHAR PRIMARY KEY,
    date_key        INTEGER NOT NULL REFERENCES dim_date(date_key),
    carrier_key     INTEGER NOT NULL REFERENCES dim_carrier(carrier_key),
    route_key       INTEGER NOT NULL REFERENCES dim_route(route_key),
    origin          VARCHAR NOT NULL,
    destination     VARCHAR NOT NULL,
    aircraft        VARCHAR NOT NULL,
    seats           INTEGER NOT NULL,
    passengers      INTEGER NOT NULL,
    dep_delay_min   INTEGER,
    arr_delay_min   INTEGER,
    delay_cause     VARCHAR,
    cancelled       BOOLEAN NOT NULL,
    status          VARCHAR NOT NULL
);
