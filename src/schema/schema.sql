CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL DEFAULT 'unknown',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_fetched_at INTEGER,
    last_status INTEGER DEFAULT 0,
    node_count INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscribe_url TEXT NOT NULL,
    source_id INTEGER,
    node_name TEXT,
    node_type TEXT NOT NULL,
    node_data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    country TEXT,
    provider TEXT,
    latency INTEGER,
    download_speed INTEGER,
    score REAL DEFAULT 0.0,
    last_checked_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_nodes_subscribe ON nodes(subscribe_url);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
CREATE INDEX IF NOT EXISTS idx_nodes_country ON nodes(country);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);

CREATE TABLE IF NOT EXISTS check_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    error_message TEXT,
    started_at INTEGER,
    finished_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

-- ===== Phase 2: Token & User 系统 =====

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    token TEXT NOT NULL UNIQUE,
    name TEXT DEFAULT 'default',
    permissions TEXT DEFAULT 'read',
    is_active INTEGER NOT NULL DEFAULT 1,
    expired_at INTEGER,
    last_used_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tokens_token ON tokens(token);
CREATE INDEX IF NOT EXISTS idx_tokens_user ON tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);