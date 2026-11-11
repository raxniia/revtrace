from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from revtrace.config import ROOT, Settings
from revtrace.dataset import Dataset
from revtrace.engine.investigation import Context
from revtrace.synth import Scenario, generate

CURRENT, BASELINE = "2026-10", "2026-09"


def make_settings(root: Path, **overrides) -> Settings:
    values = {
        "provider": "baseline",
        "model": "",
        "api_key": "",
        "base_url": "",
        "embeddings": "",
        "datasets_dir": root / "datasets",
        "var_dir": root / "var",
        "default_dataset": "demo",
        "sla_response_minutes": 30,
        "min_followups": 2,
        "max_agent_steps": 6,
    }
    return Settings(**(values | overrides))


@pytest.fixture(scope="session")
def workspace(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("revtrace")
    generate(Scenario(name="demo"), root / "datasets" / "demo")
    shutil.copytree(ROOT / "datasets" / "dar-confort" / "docs", root / "datasets" / "demo" / "docs")
    return root


@pytest.fixture(scope="session")
def settings(workspace) -> Settings:
    return make_settings(workspace)


@pytest.fixture(scope="session")
def ctx(workspace, settings) -> Context:
    return Context.build(Dataset(workspace / "datasets" / "demo"), settings)
