"""
database.py — SQLite persistence for the finance bot.
All data lives in a single finance.db file next to the bot.
"""

from __future__ import annotations

import sqlite3
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "finance.db")


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init(self):
        """Create tables if they don't exist."""
        with self._conn() as conn:
            conn.executescript("""
                -- Shared expense ledger
                CREATE TABLE IF NOT EXISTS debts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    creditor    TEXT    NOT NULL,   -- person owed money
                    debtor      TEXT    NOT NULL,   -- person who owes
                    amount      REAL    NOT NULL CHECK(amount > 0),
                    description TEXT,
                    settled     INTEGER NOT NULL DEFAULT 0,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                );

                -- Personal transactions (spends & income)
                CREATE TABLE IF NOT EXISTS transactions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount      REAL    NOT NULL CHECK(amount >= 0),
                    type        TEXT    NOT NULL CHECK(type IN ('spend','income')),
                    category    TEXT    NOT NULL DEFAULT 'other',
                    description TEXT,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                );

                -- Key-value config store (balance, etc.)
                CREATE TABLE IF NOT EXISTS config (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );

                -- Monthly budgets
                CREATE TABLE IF NOT EXISTS budgets (
                    category TEXT PRIMARY KEY,
                    amount   REAL NOT NULL CHECK(amount > 0)
                );
            """)

    # ── Debts ─────────────────────────────────────────────────────────────────

    def add_debt(self, creditor: str, debtor: str, amount: float, description: str = ""):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO debts (creditor, debtor, amount, description) VALUES (?,?,?,?)",
                (creditor.lower(), debtor.lower(), round(amount, 2), description)
            )

    def get_all_debts(self) -> list[dict]:
        """Return all unsettled debts as dicts."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM debts WHERE settled = 0 ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def clear_debt(self, person: str, amount: Optional[float] = None) -> Optional[float]:
        """
        Mark debt(s) with `person` as settled.
        If amount given, settle only up to that amount.
        Returns the total amount cleared, or None if nothing found.
        """
        person = person.lower()
        with self._conn() as conn:
            # Find debts involving this person
            rows = conn.execute(
                """SELECT * FROM debts WHERE settled = 0
                   AND (creditor = ? OR debtor = ?)
                   ORDER BY created_at""",
                (person, person)
            ).fetchall()

            if not rows:
                return None

            cleared = 0.0
            remaining = amount  # None means clear all

            for row in rows:
                if remaining is not None and remaining <= 0:
                    break
                if remaining is None:
                    # Clear fully
                    conn.execute("UPDATE debts SET settled = 1 WHERE id = ?", (row["id"],))
                    cleared += row["amount"]
                elif remaining >= row["amount"]:
                    conn.execute("UPDATE debts SET settled = 1 WHERE id = ?", (row["id"],))
                    cleared   += row["amount"]
                    remaining -= row["amount"]
                else:
                    # Partial: reduce the debt
                    new_amount = round(row["amount"] - remaining, 2)
                    conn.execute("UPDATE debts SET amount = ? WHERE id = ?", (new_amount, row["id"]))
                    cleared   += remaining
                    remaining  = 0

        return round(cleared, 2) if cleared > 0 else None

    def clear_all_debts(self):
        with self._conn() as conn:
            conn.execute("UPDATE debts SET settled = 1")

    # ── Transactions ──────────────────────────────────────────────────────────

    def add_transaction(
        self,
        amount: float,
        t_type: str,
        category: str = "other",
        description: str = "",
        created_at: Optional[str] = None,
    ):
        with self._conn() as conn:
            if created_at:
                conn.execute(
                    "INSERT INTO transactions (amount, type, category, description, created_at) VALUES (?,?,?,?,?)",
                    (round(abs(amount), 2), t_type, category, description, created_at)
                )
            else:
                conn.execute(
                    "INSERT INTO transactions (amount, type, category, description) VALUES (?,?,?,?)",
                    (round(abs(amount), 2), t_type, category, description)
                )

    def get_transactions(self, limit: int = 10) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_monthly_transactions(self, year: int, month: int) -> list[dict]:
        prefix = f"{year}-{month:02d}"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE created_at LIKE ? ORDER BY created_at DESC",
                (f"{prefix}%",)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_monthly_spend(self, category: str, year: int, month: int) -> float:
        prefix = f"{year}-{month:02d}"
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(amount), 0) as total FROM transactions
                   WHERE type='spend' AND category=? AND created_at LIKE ?""",
                (category, f"{prefix}%")
            ).fetchone()
        return float(row["total"])

    # ── Balance ───────────────────────────────────────────────────────────────

    def get_balance(self) -> Optional[float]:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM config WHERE key='balance'").fetchone()
        return float(row["value"]) if row else None

    def set_balance(self, amount: float):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('balance', ?)",
                (str(round(amount, 2)),)
            )

    def adjust_balance(self, delta: float):
        """Add delta to balance (negative = deduct). No-op if balance not set."""
        current = self.get_balance()
        if current is not None:
            self.set_balance(current + delta)

    def get_initial_balance(self) -> Optional[float]:
        """Get the initial balance set via /setbalance for alert calculations."""
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM config WHERE key='initial_balance'").fetchone()
        return float(row["value"]) if row else None

    def set_initial_balance(self, amount: float):
        """Store initial balance for percentage-based alerts."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('initial_balance', ?)",
                (str(round(amount, 2)),)
            )

    # ── Budgets ───────────────────────────────────────────────────────────────

    # ── Generic config ────────────────────────────────────────────────────────

    def get_config(self, key: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_config(self, key: str, value: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?,?)", (key, value)
            )

    # ── Budgets ───────────────────────────────────────────────────────────────

    def set_budget(self, category: str, amount: float):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO budgets (category, amount) VALUES (?,?)",
                (category.lower(), round(amount, 2))
            )

    def get_budgets(self) -> dict[str, float]:
        with self._conn() as conn:
            rows = conn.execute("SELECT category, amount FROM budgets").fetchall()
        return {r["category"]: float(r["amount"]) for r in rows}

    def delete_budget(self, category: str) -> bool:
        """Delete a budget. Returns True if deleted, False if not found."""
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM budgets WHERE category = ?", (category.lower(),))
        return cursor.rowcount > 0

    def delete_transaction(self, transaction_id: int) -> bool:
        """Delete a transaction by ID. Returns True if deleted, False if not found."""
        current_bal = self.get_balance()
        with self._conn() as conn:
            # First, get the transaction details
            row = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
            if not row:
                return False
            
            # Delete it
            cursor = conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
            
            # Reverse the balance effect
            if current_bal is not None:
                if row["type"] == "spend":
                    self.adjust_balance(row["amount"])  # Add back the spent amount
                else:  # income
                    self.adjust_balance(-row["amount"])  # Remove the income
        
        return True

    def delete_category_transactions(self, category: str, year: int, month: int) -> int:
        """Delete all transactions in a category for a specific month. Returns count deleted."""
        prefix = f"{year}-{month:02d}"
        current_bal = self.get_balance()
        
        with self._conn() as conn:
            # Get all transactions to reverse balance changes
            rows = conn.execute(
                """SELECT * FROM transactions 
                   WHERE category = ? AND created_at LIKE ? ORDER BY created_at DESC""",
                (category, f"{prefix}%")
            ).fetchall()
            
            # Calculate total to reverse
            total_spend = sum(r["amount"] for r in rows if r["type"] == "spend")
            total_income = sum(r["amount"] for r in rows if r["type"] == "income")
            
            # Delete transactions
            cursor = conn.execute(
                """DELETE FROM transactions 
                   WHERE category = ? AND created_at LIKE ?""",
                (category, f"{prefix}%")
            )
            count = cursor.rowcount
        
        # Reverse balance effects
        if current_bal is not None and count > 0:
            delta = total_spend - total_income  # net to add back
            self.adjust_balance(delta)
        
        return count