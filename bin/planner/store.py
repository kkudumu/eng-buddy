"""Plan persistence — JSON files + SQLite index."""

import sqlite3
import json
from pathlib import Path
from typing import Optional
from models import Plan


class PlanStore:
    def __init__(self, plans_dir: str, db_path: str):
        self.plans_dir = Path(plans_dir)
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                card_id INTEGER PRIMARY KEY,
                plan_id TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def save(self, plan: Plan) -> str:
        path = self.plans_dir / f"{plan.card_id}.json"
        plan.save(str(path))

        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO plans (card_id, plan_id, source, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (plan.card_id, plan.id, plan.source, plan.status, plan.created_at),
            )
            conn.commit()
        finally:
            conn.close()
        return str(path)

    def get(self, card_id: int) -> Optional[Plan]:
        path = self.plans_dir / f"{card_id}.json"
        if path.exists():
            return Plan.load(str(path))
        return None

    def delete(self, card_id: int) -> bool:
        path = self.plans_dir / f"{card_id}.json"
        if not path.exists():
            return False
        path.unlink()
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("DELETE FROM plans WHERE card_id = ?", (card_id,))
            conn.commit()
        finally:
            conn.close()
        return True

    def has_plan(self, card_id: int) -> bool:
        return (self.plans_dir / f"{card_id}.json").exists()

    def list_by_status(self, status: str) -> list:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute(
                "SELECT card_id FROM plans WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        finally:
            conn.close()
        plans = []
        for (card_id,) in rows:
            plan = self.get(card_id)
            if plan:
                plans.append(plan)
        return plans

    def cards_needing_plans(self) -> list:
        """Find cards with status 'pending' that don't have a plan yet."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("""
                SELECT c.* FROM cards c
                LEFT JOIN plans p ON c.id = p.card_id
                WHERE c.status = 'pending' AND p.card_id IS NULL
                ORDER BY c.id ASC
            """).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def get_card(self, card_id: int) -> Optional[dict]:
        """Look up a card from the inbox.db cards table."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        finally:
            conn.close()
        return dict(row) if row else None

    def update_status(self, card_id: int, status: str) -> None:
        from models import VALID_PLAN_STATUSES
        if status not in VALID_PLAN_STATUSES:
            raise ValueError(f"Invalid plan status: {status!r}. Must be one of {VALID_PLAN_STATUSES}")
        plan = self.get(card_id)
        if plan:
            plan.status = status
            self.save(plan)
