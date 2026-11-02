from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def connect(settings):
    return psycopg.connect(settings.database_url, row_factory=dict_row, connect_timeout=5)


def initialize(settings):
    with connect(settings) as conn:
        # Namespace is deliberately separate from teammate-owned tables.
        conn.execute("SELECT pg_advisory_xact_lock(714225)")
        conn.execute(Path(__file__).with_name("schema.sql").read_text())


def audit(conn, user_id, action):
    conn.execute("INSERT INTO cc_audit(user_id,action) VALUES (%s,%s)", (user_id, action))
