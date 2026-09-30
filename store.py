"""SQLite storage: tickets, per-server settings, and each member's last-used character name.

One small file (tickets.db next to bot.py). Every ticket keeps its form answers as JSON in `fields`,
so adding a form question never needs a schema change.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, fields
from pathlib import Path

DB_FILE = Path(__file__).resolve().parent / "tickets.db"

OPEN, CLAIMED, DONE, CANCELLED = "open", "claimed", "done", "cancelled"
ACTIVE = (OPEN, CLAIMED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    kind         TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'open',
    requester_id INTEGER NOT NULL,
    character    TEXT    NOT NULL DEFAULT '',
    claimer_id   INTEGER,
    fields       TEXT    NOT NULL DEFAULT '{}',
    thread_id    INTEGER UNIQUE,
    message_id   INTEGER,
    close_reason TEXT    NOT NULL DEFAULT '',
    created_at   REAL    NOT NULL,
    updated_at   REAL    NOT NULL,
    closed_at    REAL
);
CREATE INDEX IF NOT EXISTS tickets_requester ON tickets (guild_id, requester_id, status);
CREATE INDEX IF NOT EXISTS tickets_status ON tickets (guild_id, status, kind);

CREATE TABLE IF NOT EXISTS settings (
    guild_id        INTEGER PRIMARY KEY,
    forum_id        INTEGER,
    crafter_role    INTEGER,
    gatherer_role   INTEGER,
    banker_role     INTEGER,
    officer_role    INTEGER,
    panel_thread_id INTEGER
);

CREATE TABLE IF NOT EXISTS characters (
    user_id INTEGER PRIMARY KEY,
    name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bank_ledger (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    item       TEXT    NOT NULL,
    delta      INTEGER NOT NULL,
    actor_id   INTEGER NOT NULL,
    ticket_id  INTEGER,
    note       TEXT    NOT NULL DEFAULT '',
    created_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS bank_ledger_item ON bank_ledger (guild_id, item);
"""

# Columns added after the first release; ALTER TABLE keeps old databases working.
MIGRATIONS = [
    ("settings", "bank_channel_id", "INTEGER"),
    ("settings", "bank_message_id", "INTEGER"),
    ("settings", "bank_forum_id", "INTEGER"),
    ("settings", "bank_panel_thread_id", "INTEGER"),
]


@dataclass
class Ticket:
    id: int
    guild_id: int
    kind: str
    status: str
    requester_id: int
    character: str
    claimer_id: int | None
    fields: dict
    thread_id: int | None
    message_id: int | None
    close_reason: str
    created_at: float
    updated_at: float
    closed_at: float | None

    @property
    def active(self) -> bool:
        return self.status in ACTIVE


@dataclass
class Settings:
    guild_id: int
    forum_id: int | None = None
    crafter_role: int | None = None
    gatherer_role: int | None = None
    banker_role: int | None = None
    officer_role: int | None = None
    panel_thread_id: int | None = None
    bank_channel_id: int | None = None   # text channel for the inventory board (else it sits under a panel)
    bank_message_id: int | None = None
    bank_forum_id: int | None = None     # separate forum for donations and bank requests (else the main forum)
    bank_panel_thread_id: int | None = None

    def forum_for(self, kind: str) -> int | None:
        return (self.bank_forum_id or self.forum_id) if kind in ("donate", "bank") else self.forum_id


@dataclass
class LedgerEntry:
    id: int
    guild_id: int
    item: str
    delta: int
    actor_id: int
    ticket_id: int | None
    note: str
    created_at: float


class Store:
    def __init__(self, path: Path | str = DB_FILE) -> None:
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for table, column, kind in MIGRATIONS:
            if column not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        self.db.commit()

    # ---------------------------------------------------------------- tickets

    def _ticket(self, row: sqlite3.Row | None) -> Ticket | None:
        if row is None:
            return None
        d = dict(row)
        d["fields"] = json.loads(d["fields"] or "{}")
        return Ticket(**d)

    def create(self, guild_id: int, kind: str, requester_id: int, character: str, fields: dict) -> Ticket:
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO tickets (guild_id, kind, requester_id, character, fields, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, kind, requester_id, character, json.dumps(fields), now, now),
        )
        self.db.commit()
        return self.get(cur.lastrowid)

    def attach_thread(self, ticket_id: int, thread_id: int, message_id: int) -> None:
        self.db.execute("UPDATE tickets SET thread_id = ?, message_id = ? WHERE id = ?", (thread_id, message_id, ticket_id))
        self.db.commit()

    def delete(self, ticket_id: int) -> None:
        """Only for a ticket whose forum post could not be created."""
        self.db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        self.db.commit()

    def get(self, ticket_id: int) -> Ticket | None:
        return self._ticket(self.db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone())

    def by_thread(self, thread_id: int) -> Ticket | None:
        return self._ticket(self.db.execute("SELECT * FROM tickets WHERE thread_id = ?", (thread_id,)).fetchone())

    def set_status(self, ticket_id: int, status: str, claimer_id: int | None = None, reason: str = "") -> Ticket:
        """Move a ticket to `status`. Claiming records the claimer; reopening or unclaiming clears it;
        closing keeps it so the post still says who did the work."""
        now = time.time()
        t = self.get(ticket_id)
        if status == CLAIMED:
            claimer = claimer_id
        elif status == OPEN:
            claimer = None
        else:
            claimer = claimer_id if claimer_id is not None else t.claimer_id
        closed_at = now if status in (DONE, CANCELLED) else None
        self.db.execute(
            "UPDATE tickets SET status = ?, claimer_id = ?, close_reason = ?, updated_at = ?, closed_at = ? WHERE id = ?",
            (status, claimer, reason if status in (DONE, CANCELLED) else "", now, closed_at, ticket_id),
        )
        self.db.commit()
        return self.get(ticket_id)

    def mine(self, guild_id: int, user_id: int, limit: int = 25) -> list[Ticket]:
        rows = self.db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND requester_id = ? AND status IN ('open', 'claimed')"
            " AND thread_id IS NOT NULL ORDER BY created_at LIMIT ?",
            (guild_id, user_id, limit),
        ).fetchall()
        return [self._ticket(r) for r in rows]

    def active(self, guild_id: int, kinds: tuple[str, ...] | None = None) -> list[Ticket]:
        rows = self.db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND status IN ('open', 'claimed') AND thread_id IS NOT NULL"
            " ORDER BY created_at",
            (guild_id,),
        ).fetchall()
        out = [self._ticket(r) for r in rows]
        return [t for t in out if kinds is None or t.kind in kinds]

    # ---------------------------------------------------------------- settings

    def settings(self, guild_id: int) -> Settings:
        row = self.db.execute("SELECT * FROM settings WHERE guild_id = ?", (guild_id,)).fetchone()
        return Settings(**dict(row)) if row else Settings(guild_id=guild_id)

    def save_settings(self, s: Settings) -> None:
        cols = [f.name for f in fields(Settings)]
        self.db.execute(
            f"INSERT INTO settings ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
            " ON CONFLICT (guild_id) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in cols[1:]),
            [getattr(s, c) for c in cols],
        )
        self.db.commit()

    # ---------------------------------------------------------------- guild bank ledger

    def bank_change(self, guild_id: int, item: str, delta: int, actor_id: int, ticket_id: int | None = None,
                    note: str = "") -> int:
        """Record items going in (+) or out (-). Returns the item's new count."""
        self.db.execute(
            "INSERT INTO bank_ledger (guild_id, item, delta, actor_id, ticket_id, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, item, delta, actor_id, ticket_id, note, time.time()),
        )
        self.db.commit()
        return self.bank_count(guild_id, item)

    def bank_count(self, guild_id: int, item: str) -> int:
        row = self.db.execute("SELECT COALESCE(SUM(delta), 0) AS n FROM bank_ledger WHERE guild_id = ? AND item = ?",
                              (guild_id, item)).fetchone()
        return int(row["n"])

    def bank_stock(self, guild_id: int) -> list[tuple[str, int]]:
        """Everything with a positive count, alphabetical."""
        rows = self.db.execute(
            "SELECT item, SUM(delta) AS n FROM bank_ledger WHERE guild_id = ? GROUP BY item HAVING n > 0 ORDER BY item",
            (guild_id,)).fetchall()
        return [(r["item"], int(r["n"])) for r in rows]

    def bank_items_like(self, guild_id: int, query: str, limit: int = 25) -> list[str]:
        rows = self.db.execute(
            "SELECT item FROM bank_ledger WHERE guild_id = ? AND item LIKE ? GROUP BY item HAVING SUM(delta) > 0"
            " ORDER BY item LIMIT ?", (guild_id, f"%{query}%", limit)).fetchall()
        return [r["item"] for r in rows]

    def bank_history(self, guild_id: int, item: str | None = None, limit: int = 15) -> list[LedgerEntry]:
        sql, args = "SELECT * FROM bank_ledger WHERE guild_id = ?", [guild_id]
        if item:
            sql, args = sql + " AND item = ?", args + [item]
        rows = self.db.execute(sql + " ORDER BY id DESC LIMIT ?", args + [limit]).fetchall()
        return [LedgerEntry(**dict(r)) for r in rows]

    # ---------------------------------------------------------------- character names

    def character(self, user_id: int) -> str:
        row = self.db.execute("SELECT name FROM characters WHERE user_id = ?", (user_id,)).fetchone()
        return row["name"] if row else ""

    def remember_character(self, user_id: int, name: str) -> None:
        self.db.execute(
            "INSERT INTO characters (user_id, name) VALUES (?, ?) ON CONFLICT (user_id) DO UPDATE SET name = excluded.name",
            (user_id, name),
        )
        self.db.commit()
