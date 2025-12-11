#!/usr/bin/env python3
"""
SQLite helper for the CashApp.

Provides:
- init_db(conn): ensure table exists
- get_all(conn): return list of rows as dicts
- insert(conn, date, group, description, amount) -> lastrowid
- delete_ids(conn, ids)
- clear_all(conn)
"""
import sqlite3
from typing import List, Dict, Any

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    "group" TEXT NOT NULL,
    description TEXT,
    amount REAL NOT NULL
);
"""

def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(CREATE_SQL)
    conn.commit()

def get_all(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute("SELECT id, date, \"group\", description, amount FROM transactions ORDER BY id")
    rows = cur.fetchall()
    cols = ["id", "date", "group", "description", "amount"]
    result = []
    for r in rows:
        result.append(dict(zip(cols, r)))
    return result

def insert(conn: sqlite3.Connection, date: str, group: str, description: str, amount: float) -> int:
    cur = conn.cursor()
    cur.execute("INSERT INTO transactions (date, \"group\", description, amount) VALUES (?, ?, ?, ?)", (date, group, description, amount))
    conn.commit()
    return cur.lastrowid

def delete_ids(conn: sqlite3.Connection, ids: List[int]):
    if not ids:
        return
    cur = conn.cursor()
    # build parameter placeholders
    placeholders = ",".join("?" for _ in ids)
    cur.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", tuple(ids))
    conn.commit()

def clear_all(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("DELETE FROM transactions")
    conn.commit()