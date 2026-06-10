"""Offline tests for scripts/run_arb_scanner.py — fake clock, injected seams."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "run_arb_scanner",
    Path(__file__).resolve().parents[2] / "scripts" / "run_arb_scanner.py",
)
assert _SPEC and _SPEC.loader
ras = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ras)


def _events() -> list[dict]:
    return [{
        "id": "ev1", "slug": "ev1", "negRisk": True,
        "markets": [
            {"conditionId": "0xc1", "clobTokenIds": '["y1", "n1"]',
             "volume24hr": 1.0, "category": "geopolitics"},
            {"conditionId": "0xc2", "clobTokenIds": '["y2", "n2"]',
             "volume24hr": 1.0, "category": "geopolitics"},
        ],
    }]


def _books(_ids: list[str], **_: object) -> dict:
    from decimal import Decimal as D
    book = {"bids": [], "asks": [(D("0.40"), D("600"))]}
    book2 = {"bids": [], "asks": [(D("0.55"), D("600"))]}
    empty = {"bids": [], "asks": []}
    return {"y1": book, "y2": book2, "n1": empty, "n2": empty}


def test_one_scan_writes_snapshot_with_violation(tmp_path: Path) -> None:
    out_dir = tmp_path / "scans"
    ras.main_loop(
        interval=120, max_books=100, out_dir=out_dir, max_scans=1,
        get_events=lambda: _events(), get_books=_books, sleep=lambda _s: None,
    )
    files = list(out_dir.glob("*.jsonl"))
    assert len(files) == 1
    snap = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert snap["n_events"] == 1
    assert snap["n_books"] == 4
    assert snap["universe_truncated"] is False
    assert len(snap["violations"]) == 1
    assert snap["violations"][0]["type"] == "buy_all"


def test_keyboard_interrupt_in_sleep_exits_cleanly(tmp_path: Path) -> None:
    def boom(_s: float) -> None:
        raise KeyboardInterrupt

    ras.main_loop(
        interval=120, max_books=100, out_dir=tmp_path / "s", max_scans=5,
        get_events=lambda: _events(), get_books=_books, sleep=boom,
    )  # must return, not raise
    assert len(list((tmp_path / "s").glob("*.jsonl"))) == 1


def test_universe_refresh_failure_reuses_previous(tmp_path: Path) -> None:
    calls = {"n": 0}

    def flaky_events() -> list[dict]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("gamma down")
        return _events()

    ras.main_loop(
        interval=120, max_books=100, out_dir=tmp_path / "s", max_scans=2,
        refresh_every=1, get_events=flaky_events, get_books=_books,
        sleep=lambda _s: None,
    )
    lines = (
        next((tmp_path / "s").glob("*.jsonl")).read_text(encoding="utf-8")
        .strip().splitlines()
    )
    assert len(lines) == 2  # second scan ran on the previous universe


def test_scan_failure_does_not_kill_loop(tmp_path: Path) -> None:
    calls = {"n": 0}

    def flaky_books(ids: list[str], **kw: object) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("network blip")
        return _books(ids, **kw)

    ras.main_loop(
        interval=120, max_books=100, out_dir=tmp_path / "s", max_scans=2,
        refresh_every=10, get_events=lambda: _events(), get_books=flaky_books,
        sleep=lambda _s: None,
    )
    files = list((tmp_path / "s").glob("*.jsonl"))
    assert len(files) == 1
    # scan 0 failed (no line), scan 1 succeeded (one line)
    assert len(files[0].read_text(encoding="utf-8").strip().splitlines()) == 1
