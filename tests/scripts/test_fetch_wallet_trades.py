# tests/scripts/test_fetch_wallet_trades.py
"""Offline tests for scripts/fetch_wallet_trades.py — no real network calls."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "fetch_wallet_trades",
    Path(__file__).resolve().parents[2] / "scripts" / "fetch_wallet_trades.py",
)
assert _SPEC and _SPEC.loader
fwt = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fwt)

from pat.venues.polymarket.leaderboard import LeaderEntry  # noqa: E402

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

_FAKE_WALLETS = ["0xaaa", "0xbbb"]

_ALL_TRADES = [
    {
        "transactionHash": "0x1",
        "asset": "tok1",
        "size": "10",
        "side": "BUY",
        "price": "0.4",
        "timestamp": 100,
        "conditionId": "0xc",
    },
    {
        "transactionHash": "0x2",
        "asset": "tok2",
        "size": "5",
        "side": "SELL",
        "price": "0.6",
        "timestamp": 200,
        "conditionId": "0xc",
    },
]

# takerOnly=True returns only the second trade (index 1) — so tx 0x1 is maker
_TAKER_TRADES = [_ALL_TRADES[1]]


def _make_leaders() -> list[LeaderEntry]:
    return [
        LeaderEntry(rank=1, wallet=w, user_name="u", vol=0, pnl=0)
        for w in _FAKE_WALLETS
    ]


def _make_control_src(tmp_path: Path) -> Path:
    # Minimal control_events with distinct maker/taker addresses
    events = [
        {"maker": "0xcontrol1", "taker": "0xcontrol2"},
        {"maker": "0xcontrol3", "taker": "0xcontrol4"},
        {"maker": "0xcontrol5", "taker": "0xcontrol6"},
    ]
    p = tmp_path / "ctrl_events.json"
    p.write_text(json.dumps(events), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_winner_and_control_list_files_written(tmp_path: Path) -> None:
    ctrl_src = _make_control_src(tmp_path)
    call_counts: dict[str, int] = {"n": 0}

    def stub_fetch(wallet: str, *, taker_only: bool, max_trades: int = 2000) -> list:
        call_counts["n"] += 1
        return _TAKER_TRADES if taker_only else _ALL_TRADES

    out = fwt.run(
        tmp_path / "out",
        top_n=2,
        control_n=3,
        control_src=ctrl_src,
        max_trades=2000,
        refresh=False,
        get_leaderboard=lambda **_: _make_leaders(),
        fetch_trades=stub_fetch,
    )

    assert (out / "_winners.json").exists()
    assert (out / "_control.json").exists()
    winners = json.loads((out / "_winners.json").read_text())
    assert set(winners) == set(_FAKE_WALLETS)


def test_per_wallet_files_written_with_is_maker(tmp_path: Path) -> None:
    ctrl_src = _make_control_src(tmp_path)

    def stub_fetch(wallet: str, *, taker_only: bool, max_trades: int = 2000) -> list:
        return _TAKER_TRADES if taker_only else _ALL_TRADES

    out_dir = tmp_path / "out"
    fwt.run(
        out_dir,
        top_n=2,
        control_n=0,
        control_src=ctrl_src,
        max_trades=2000,
        refresh=False,
        get_leaderboard=lambda **_: _make_leaders(),
        fetch_trades=stub_fetch,
    )

    for wallet in _FAKE_WALLETS:
        wf = out_dir / f"{wallet}.json"
        assert wf.exists(), f"missing {wf}"
        trades = json.loads(wf.read_text())
        assert all("is_maker" in t for t in trades), "is_maker key missing"
        # tx 0x1 is NOT in taker list -> is_maker=True; tx 0x2 IS -> is_maker=False
        by_hash = {t["transactionHash"]: t for t in trades}
        assert by_hash["0x1"]["is_maker"] is True
        assert by_hash["0x2"]["is_maker"] is False


def test_idempotent_skip_when_file_exists(tmp_path: Path) -> None:
    """Second run without refresh=True must not call fetch_trades again."""
    ctrl_src = _make_control_src(tmp_path)
    call_counts: dict[str, int] = {"n": 0}

    def counting_fetch(wallet: str, *, taker_only: bool, max_trades: int = 2000) -> list:
        call_counts["n"] += 1
        return _TAKER_TRADES if taker_only else _ALL_TRADES

    common = {
        "top_n": 2,
        "control_n": 0,
        "control_src": ctrl_src,
        "max_trades": 2000,
        "get_leaderboard": lambda **_: _make_leaders(),
        "fetch_trades": counting_fetch,
    }

    out_dir = tmp_path / "out"
    fwt.run(out_dir, refresh=False, **common)
    count_after_first = call_counts["n"]
    assert count_after_first > 0

    # Second run — files already exist, refresh=False
    fwt.run(out_dir, refresh=False, **common)
    assert call_counts["n"] == count_after_first, (
        "fetch_trades was called on a 2nd run without refresh — idempotency broken"
    )


def test_refresh_re_fetches_existing_files(tmp_path: Path) -> None:
    ctrl_src = _make_control_src(tmp_path)
    call_counts: dict[str, int] = {"n": 0}

    def counting_fetch(wallet: str, *, taker_only: bool, max_trades: int = 2000) -> list:
        call_counts["n"] += 1
        return _TAKER_TRADES if taker_only else _ALL_TRADES

    common = {
        "top_n": 2,
        "control_n": 0,
        "control_src": ctrl_src,
        "max_trades": 2000,
        "get_leaderboard": lambda **_: _make_leaders(),
        "fetch_trades": counting_fetch,
    }

    out_dir = tmp_path / "out"
    fwt.run(out_dir, refresh=False, **common)
    count_after_first = call_counts["n"]

    # Second run with refresh=True — must re-fetch
    fwt.run(out_dir, refresh=True, **common)
    assert call_counts["n"] > count_after_first
