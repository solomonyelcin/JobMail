"""Tiny database layer supporting SQLite (local/dev/tests) and PostgreSQL (production).

SQL is written once with `?` placeholders and translated for PostgreSQL.
All timestamps are stored as ISO-8601 UTC strings so ordering works on both engines.
"""
import sqlite3


class Conn:
    def __init__(self, raw, is_pg):
        self.raw = raw
        self.is_pg = is_pg

    def execute(self, sql, params=()):
        if self.is_pg:
            sql = sql.replace("?", "%s")
        cur = self.raw.cursor()
        cur.execute(sql, tuple(params))
        return cur

    def all(self, sql, params=()):
        cur = self.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def one(self, sql, params=()):
        cur = self.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


class Database:
    def __init__(self, url):
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        self.url = url
        self.is_pg = url.startswith("postgresql://")
        if not self.is_pg:
            if not url.startswith("sqlite:///"):
                raise ValueError("DATABASE_URL must start with postgresql:// or sqlite:///")
            self.path = url[len("sqlite:///"):] or ":memory:"
            self._shared = None
            if self.path == ":memory:":
                # one shared connection so tests see the same in-memory database
                self._shared = sqlite3.connect(":memory:", check_same_thread=False)
                self._shared.row_factory = sqlite3.Row

    def connect(self) -> Conn:
        if self.is_pg:
            import psycopg
            from psycopg.rows import dict_row

            return Conn(psycopg.connect(self.url, row_factory=dict_row), True)
        if self._shared is not None:
            return Conn(_NoClose(self._shared), False)
        raw = sqlite3.connect(self.path, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys=ON")
        return Conn(raw, False)

    def init_schema(self):
        pk = "SERIAL PRIMARY KEY" if self.is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        conn = self.connect()
        stmts = [
            f"""CREATE TABLE IF NOT EXISTS accounts (
                id {pk},
                email TEXT UNIQUE NOT NULL,
                refresh_token_enc TEXT,
                created_at TEXT NOT NULL,
                last_sync_at TEXT
            )""",
            f"""CREATE TABLE IF NOT EXISTS applications (
                id {pk},
                company TEXT NOT NULL,
                company_key TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                role_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'applied',
                notes TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'auto',
                status_locked INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                last_activity_at TEXT NOT NULL,
                UNIQUE (company_key, role_key)
            )""",
            f"""CREATE TABLE IF NOT EXISTS emails (
                id {pk},
                gmail_id TEXT UNIQUE NOT NULL,
                thread_id TEXT,
                subject TEXT NOT NULL DEFAULT '',
                sender TEXT NOT NULL DEFAULT '',
                sender_email TEXT NOT NULL DEFAULT '',
                snippet TEXT NOT NULL DEFAULT '',
                body_text TEXT NOT NULL DEFAULT '',
                received_at TEXT NOT NULL,
                category TEXT NOT NULL,
                company TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '',
                application_id INTEGER REFERENCES applications(id) ON DELETE SET NULL
            )""",
            "CREATE TABLE IF NOT EXISTS seen_messages (gmail_id TEXT PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS idx_emails_received ON emails (received_at)",
            "CREATE INDEX IF NOT EXISTS idx_emails_category ON emails (category)",
            "CREATE INDEX IF NOT EXISTS idx_emails_app ON emails (application_id)",
        ]
        for s in stmts:
            conn.execute(s)
        conn.commit()
        conn.close()


class _NoClose:
    """Wraps the shared in-memory connection so per-request close() is a no-op."""

    def __init__(self, c):
        self._c = c

    def cursor(self):
        return self._c.cursor()

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        pass
