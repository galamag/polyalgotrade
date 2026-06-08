from __future__ import annotations

import json
from pathlib import Path

from pat.venues.polymarket.gamma import select_geopolitics_tokens

FIX = Path(__file__).parents[2] / "data" / "fixtures"


def test_select_keeps_only_feesenabled_false_tokens() -> None:
    events = [
        {"markets": [
            {"feesEnabled": False, "clobTokenIds": ["111", "222"]},
            {"feesEnabled": True, "clobTokenIds": ["333", "444"]},
        ]},
    ]
    assert select_geopolitics_tokens(events) == {"111", "222"}


def test_select_handles_clobtokenids_as_json_string() -> None:
    # Real Gamma sometimes returns clobTokenIds as a JSON-encoded string, not an array.
    events = [{"markets": [{"feesEnabled": False, "clobTokenIds": "[\"555\", \"666\"]"}]}]
    assert select_geopolitics_tokens(events) == {"555", "666"}


def test_select_excludes_market_missing_feesenabled() -> None:
    # Conservative: only explicit feesEnabled is False is treated as 0%-fee.
    events = [{"markets": [{"clobTokenIds": ["999"]}]}]
    assert select_geopolitics_tokens(events) == set()


def test_select_from_fixture() -> None:
    events = json.loads((FIX / "gamma_events_sample.json").read_text(encoding="utf-8"))
    assert select_geopolitics_tokens(events) == {"111", "222", "555", "666"}


def test_select_cross_check_drops_nonzero_base_fee() -> None:
    events = [{"markets": [{"feesEnabled": False, "clobTokenIds": ["111", "222"]}]}]
    fee_rates = {"111": 0, "222": 5}  # 222 actually charges 5 bps -> drop it

    tokens = select_geopolitics_tokens(
        events, cross_check=True, get_fee_rate=lambda token_id: fee_rates[token_id]
    )
    assert tokens == {"111"}
