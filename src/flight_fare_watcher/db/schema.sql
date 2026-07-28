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
    created_at TEXT NOT NULL
);

-- COALESCE(return_date, '') because SQLite's UNIQUE treats NULL as distinct
-- from NULL, which would let duplicate one-way watches (return_date IS NULL)
-- slip through a plain column-based UNIQUE constraint.
CREATE UNIQUE INDEX IF NOT EXISTS idx_watched_routes_unique
    ON watched_routes(origin, destination, depart_date, COALESCE(return_date, ''));

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
    scraped_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fares_route_lookup
    ON fares(origin, destination, depart_date, return_date);

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
