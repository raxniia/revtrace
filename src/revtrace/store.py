from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from .engine.schema import now

SCHEMA = """
create table if not exists investigations (
    id text primary key,
    dataset text not null,
    question text not null,
    engine text not null,
    status text not null,
    error text,
    created_at text not null,
    report text,
    events text
);
create table if not exists actions (
    id text primary key,
    investigation_id text not null,
    recommendation_id text not null,
    title text not null,
    type text not null,
    label text not null,
    payload text not null,
    status text not null,
    created_at text not null,
    decided_at text,
    result text
);
create table if not exists outbox (
    id text primary key,
    action_id text not null,
    kind text not null,
    lead_id text,
    title text not null,
    body text,
    due_at text,
    created_at text not null
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        with self._lock:
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            finally:
                db.close()

    def create_investigation(self, investigation_id: str, dataset: str, question: str, engine: str) -> None:
        with self._connect() as db:
            db.execute(
                "insert into investigations (id, dataset, question, engine, status, created_at) values (?,?,?,?,?,?)",
                (investigation_id, dataset, question, engine, "running", now()),
            )

    def finish_investigation(
        self, investigation_id: str, report: dict | None, events: list[dict], error: str = ""
    ) -> None:
        with self._connect() as db:
            db.execute(
                "update investigations set status=?, error=?, report=?, events=? where id=?",
                (
                    "failed" if error else "complete",
                    error or None,
                    json.dumps(report) if report else None,
                    json.dumps(events),
                    investigation_id,
                ),
            )

    def investigation(self, investigation_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("select * from investigations where id=?", (investigation_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["report"] = json.loads(record["report"]) if record["report"] else None
        record["events"] = json.loads(record["events"]) if record["events"] else []
        return record

    def investigations(self, dataset: str | None = None, limit: int = 30) -> list[dict]:
        query = "select id, dataset, question, engine, status, error, created_at from investigations"
        params: tuple = ()
        if dataset:
            query += " where dataset=?"
            params = (dataset,)
        with self._connect() as db:
            rows = db.execute(query + " order by created_at desc limit ?", (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def add_action(self, investigation_id: str, recommendation_id: str, title: str, action: dict) -> str:
        action_id = uuid.uuid4().hex[:10]
        with self._connect() as db:
            db.execute(
                "insert into actions (id, investigation_id, recommendation_id, title, type, label, payload, status, created_at)"
                " values (?,?,?,?,?,?,?,?,?)",
                (
                    action_id,
                    investigation_id,
                    recommendation_id,
                    title,
                    action["type"],
                    action["label"],
                    json.dumps(action["payload"]),
                    "pending",
                    now(),
                ),
            )
        return action_id

    def _action(self, row: sqlite3.Row) -> dict:
        record = dict(row)
        record["payload"] = json.loads(record["payload"])
        record["result"] = json.loads(record["result"]) if record["result"] else None
        return record

    def action(self, action_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("select * from actions where id=?", (action_id,)).fetchone()
        return self._action(row) if row else None

    def actions(self, investigation_id: str | None = None) -> list[dict]:
        query, params = "select * from actions", ()
        if investigation_id:
            query, params = query + " where investigation_id=?", (investigation_id,)
        with self._connect() as db:
            rows = db.execute(query + " order by created_at desc", params).fetchall()
        return [self._action(r) for r in rows]

    def decide_action(self, action_id: str, status: str, result: dict | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "update actions set status=?, decided_at=?, result=? where id=?",
                (status, now(), json.dumps(result) if result else None, action_id),
            )

    def add_outbox(
        self,
        action_id: str,
        kind: str,
        title: str,
        body: str = "",
        lead_id: str | None = None,
        due_at: str | None = None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                "insert into outbox (id, action_id, kind, lead_id, title, body, due_at, created_at) values (?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex[:10], action_id, kind, lead_id, title, body, due_at, now()),
            )

    def outbox(self, action_id: str | None = None) -> list[dict]:
        query, params = "select * from outbox", ()
        if action_id:
            query, params = query + " where action_id=?", (action_id,)
        with self._connect() as db:
            rows = db.execute(query + " order by created_at desc", params).fetchall()
        return [dict(r) for r in rows]
