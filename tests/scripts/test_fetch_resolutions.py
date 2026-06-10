"""Offline tests for scripts/fetch_resolutions.py — idempotency + unknown recording."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "fetch_resolutions",
    Path(__file__).resolve().parents[2] / "scripts" / "fetch_resolutions.py",
)
assert _SPEC and _SPEC.loader
fr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fr)


def _trades_dir(tmp_path: Path) -> Path:
    d = tmp_path / "trades"
    d.mkdir()
    rows = [
        {"conditionId": "0xres", "eventSlug": "e1", "asset": "a", "side": "BUY",
         "price": "0.4", "size": "1", "outcomeIndex": 0, "timestamp": 1},
        {"conditionId": "0xopen", "eventSlug": "e2", "asset": "b", "side": "BUY",
         "price": "0.4", "size": "1", "outcomeIndex": 0, "timestamp": 2},
        {"conditionId": "0xgone", "eventSlug": "e3", "asset": "c", "side": "BUY",
         "price": "0.4", "size": "1", "outcomeIndex": 0, "timestamp": 3},
    ]
    (d / "0xaaa.json").write_text(json.dumps(rows), encoding="utf-8")
    return d


def _fake_markets(chunks_seen: list[list[str]]):
    def fake(ids: list[str], **_: object) -> list[dict]:
        chunks_seen.append(list(ids))
        out = []
        if "0xres" in ids:
            out.append({"conditionId": "0xres", "closed": True,
                        "outcomePrices": '["1", "0"]'})
        if "0xopen" in ids:
            out.append({"conditionId": "0xopen", "closed": False,
                        "outcomePrices": '["0.6", "0.4"]'})
        # 0xgone never comes back -> unknown
        return out

    return fake


def test_fetch_writes_records_and_unknown(tmp_path: Path) -> None:
    trades = _trades_dir(tmp_path)
    out = tmp_path / "resolutions.json"
    calls: list[list[str]] = []
    fr.run(trades, out, fetch_markets=_fake_markets(calls))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["0xres"] == {"status": "resolved", "winning_index": 0}
    assert data["0xopen"]["status"] == "unresolved"
    assert data["0xgone"]["status"] == "unknown"


def test_second_run_without_refresh_fetches_nothing(tmp_path: Path) -> None:
    trades = _trades_dir(tmp_path)
    out = tmp_path / "resolutions.json"
    fr.run(trades, out, fetch_markets=_fake_markets([]))
    calls: list[list[str]] = []
    fr.run(trades, out, fetch_markets=_fake_markets(calls))
    assert calls == []  # everything already recorded


def test_refresh_refetches_only_non_final(tmp_path: Path) -> None:
    trades = _trades_dir(tmp_path)
    out = tmp_path / "resolutions.json"
    fr.run(trades, out, fetch_markets=_fake_markets([]))
    calls: list[list[str]] = []
    fr.run(trades, out, refresh=True, fetch_markets=_fake_markets(calls))
    refetched = {c for chunk in calls for c in chunk}
    assert refetched == {"0xopen", "0xgone"}  # resolved is final, never re-fetched
