"""Offline tests for scripts/run_resolution_screen.py — report + verdict + jsonl."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_resolution_screen",
    Path(__file__).resolve().parents[2] / "scripts" / "run_resolution_screen.py",
)
assert _SPEC and _SPEC.loader
rrs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rrs)


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    trades_dir = tmp_path / "trades"
    trades_dir.mkdir()

    def _rows(cond: str, slug: str, price: str) -> list[dict]:
        return [
            {"conditionId": cond, "eventSlug": slug, "asset": f"tok-{cond}",
             "side": "BUY", "price": price, "size": "10", "outcomeIndex": 0,
             "timestamp": 1}
        ]

    # winner W1: one winning resolved event; winner W2: one losing event
    (trades_dir / "0xw1.json").write_text(
        json.dumps(_rows("0xc1", "ev-1", "0.4")), encoding="utf-8")
    (trades_dir / "0xw2.json").write_text(
        json.dumps(_rows("0xc2", "ev-2", "0.6")), encoding="utf-8")
    (trades_dir / "0xctl.json").write_text(
        json.dumps(_rows("0xc1", "ev-1", "0.5")), encoding="utf-8")
    (trades_dir / "_winners.json").write_text(
        json.dumps(["0xw1", "0xw2"]), encoding="utf-8")
    (trades_dir / "_control.json").write_text(json.dumps(["0xctl"]), encoding="utf-8")

    res_path = tmp_path / "resolutions.json"
    res_path.write_text(json.dumps({
        "0xc1": {"status": "resolved", "winning_index": 0},
        "0xc2": {"status": "resolved", "winning_index": 1},
    }), encoding="utf-8")
    return trades_dir, res_path


def test_run_writes_report_with_kill_verdict_and_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # jsonl goes to ./logs/
    trades_dir, res_path = _setup(tmp_path)
    out = tmp_path / "report.md"
    rrs.run(trades_dir, res_path, out)
    md = out.read_text(encoding="utf-8")
    assert "KILL" in md  # 0 diversified < 5
    assert "n_diversified = 0" in md
    assert "0xw1" in md  # per-wallet winners table
    jsonl = (tmp_path / "logs" / "resolution_features.jsonl").read_text(encoding="utf-8")
    recs = [json.loads(line) for line in jsonl.strip().splitlines()]
    assert {r["wallet"] for r in recs} == {"0xw1", "0xw2", "0xctl"}
    assert {r["group"] for r in recs} == {"winner", "control"}


def test_missing_wallet_file_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    trades_dir, res_path = _setup(tmp_path)
    winners = json.loads((trades_dir / "_winners.json").read_text()) + ["0xghost"]
    (trades_dir / "_winners.json").write_text(json.dumps(winners), encoding="utf-8")
    out = tmp_path / "report.md"
    rrs.run(trades_dir, res_path, out)
    assert "0xghost" not in out.read_text(encoding="utf-8")
