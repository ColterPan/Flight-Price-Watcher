-- Schema for a fresh database. Existing databases are brought up to this
-- shape by db/database.py::_apply_migrations(), which adds any missing column
-- rather than recreating tables, so local fare history survives an upgrade.

CREATE TABLE IF NOT EXISTS watched_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    return_date TEXT,
    target_price REAL,
    currency TEXT NOT NULL DEFAULT 'USD',
    alert_email TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,

    -- Search options this watch should be re-checked with. A watch for 2
    -- passengers in business is a different watch from 1 in economy, and
    -- re-checking it with different options would compare unlike prices.
    adults INTEGER NOT NULL DEFAULT 1,
    cabin TEXT NOT NULL DEFAULT 'economy',
    max_stops INTEGER,

    -- Outcome of the most recent background check, so the UI can show when a
    -- watch was last checked and what it found without scanning `fares`.
    last_checked_at TEXT,
    last_status TEXT,
    last_price REAL
);

-- COALESCE(return_date, '') because SQLite's UNIQUE treats NULL as distinct
-- from NULL, which would let duplicate one-way watches (return_date IS NULL)
-- slip through a plain column-based UNIQUE constraint. adults/cabin are part
-- of the key so the same route can be watched for different party sizes.
CREATE UNIQUE INDEX IF NOT EXISTS idx_watched_routes_unique
    ON watched_routes(
        origin, destination, depart_date, COALESCE(return_date, ''), adults, cabin
    );

CREATE TABLE IF NOT EXISTS fares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watched_route_id INTEGER REFERENCES watched_routes(id),
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    return_date TEXT,
    site TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    deep_link TEXT NOT NULL,
    scraped_at TEXT NOT NULL,

    -- Search options these fares were priced under. Price history must be
    -- compared only within the same options, or a cheap 1-passenger economy
    -- fare would look like a price drop on a 2-passenger business watch.
    adults INTEGER NOT NULL DEFAULT 1,
    cabin TEXT NOT NULL DEFAULT 'economy',

    -- Itinerary detail, so history rows can be shown as flights rather than
    -- as bare numbers.
    airline TEXT,
    carrier_code TEXT,
    stops INTEGER,
    duration_minutes INTEGER,
    depart_time TEXT,
    arrive_time TEXT,
    booking_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_fares_route_lookup
    ON fares(origin, destination, depart_date, return_date, adults, cabin);

CREATE INDEX IF NOT EXISTS idx_fares_scraped_at ON fares(scraped_at);

CREATE TABLE IF NOT EXISTS alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watched_route_id INTEGER NOT NULL REFERENCES watched_routes(id),
    fare_id INTEGER NOT NULL REFERENCES fares(id),
    sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_scrape_health_checked_at ON scrape_health(checked_at);
