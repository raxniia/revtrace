from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from revtrace import api
from revtrace.mcp_server import build_server
from revtrace.service import Service

from .conftest import make_settings


@pytest.fixture(scope="module")
def service(workspace, tmp_path_factory):
    return Service(make_settings(workspace, var_dir=tmp_path_factory.mktemp("var")))


@pytest.fixture(scope="module")
def client(service):
    app = api.create_app()
    app.dependency_overrides[api.get_service] = lambda: service
    return TestClient(app)


def test_overview_reports_health_and_signals(client):
    body = client.get("/api/overview").json()
    assert body["current"] == "2026-10" and body["baseline"] == "2026-09"
    assert 0 <= body["health"]["score"] <= 100
    assert body["signals"][0]["label"] == "primary"
    assert len(body["series"]) > 80


def test_investigation_streams_then_actions_need_approval(client):
    started = client.post("/api/investigations", json={"question": "Why did sales drop?"})
    assert started.status_code == 202
    investigation_id = started.json()["id"]

    with client.stream("GET", f"/api/investigations/{investigation_id}/events") as stream:
        frames = [line for line in stream.iter_lines() if line.startswith("data: ")]
    events = [json.loads(f[6:]) for f in frames[:-1]]
    assert events[0]["kind"] == "stage" and events[-1]["kind"] == "done"

    record = client.get(f"/api/investigations/{investigation_id}").json()
    assert record["status"] == "complete"
    pending = [a for a in record["actions"] if a["status"] == "pending"]
    assert len(pending) >= 2

    tasks = next(a for a in pending if a["type"] == "followup_tasks")
    approved = client.post(f"/api/actions/{tasks['id']}/decision", json={"approve": True}).json()
    assert approved["status"] == "executed"
    outbox = client.get("/api/actions").json()["outbox"]
    assert sum(1 for o in outbox if o["action_id"] == tasks["id"]) == len(tasks["payload"]["lead_ids"])

    again = client.post(f"/api/actions/{tasks['id']}/decision", json={"approve": True})
    assert again.status_code == 400

    other = next(a for a in pending if a["id"] != tasks["id"])
    rejected = client.post(f"/api/actions/{other['id']}/decision", json={"approve": False}).json()
    assert rejected["status"] == "rejected"


def test_agentic_mode_without_a_provider_is_refused(client):
    response = client.post("/api/investigations", json={"question": "Why?", "mode": "agentic"})
    assert response.status_code == 400 and "provider" in response.json()["detail"]


def test_upload_validates_the_dataset(client):
    bad = client.post(
        "/api/datasets", data={"name": "Broken"}, files=[("files", ("leads.csv", b"a,b\n1,2\n"))]
    )
    assert bad.status_code == 400 and "missing columns" in bad.json()["detail"]

    rows = ["lead_id,created_at,status,product"]
    rows += [
        f"L{i},2026-0{1 + i % 2}-1{i % 9},{'won' if i % 4 == 0 else 'lost'},{'A' if i % 3 else 'B'}"
        for i in range(80)
    ]
    good = client.post(
        "/api/datasets",
        data={"name": "Tiny Shop"},
        files=[("files", ("leads.csv", "\n".join(rows).encode()))],
    )
    assert good.status_code == 201 and good.json()["name"] == "tiny-shop"
    assert client.get("/api/overview", params={"dataset": "tiny-shop"}).status_code == 200


def test_mcp_server_exposes_the_toolkit(service):
    server = build_server(service)
    tools = {t.name for t in asyncio.run(server.list_tools())}
    assert {"test_factor", "search_conversations", "search_policies", "run_investigation"} <= tools
    assert not any("approve" in name or "decision" in name for name in tools)
