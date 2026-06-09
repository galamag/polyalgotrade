# tests/scripts/test_fetch_wallet_histories.py
from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "fetch_wallet_histories",
    Path(__file__).resolve().parents[2] / "scripts" / "fetch_wallet_histories.py",
)
assert _SPEC and _SPEC.loader
fwh = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fwh)


def test_topic0_histogram_counts_orderfilled_share() -> None:
    logs = [
        {"topics": ["0xV2OF"], "transactionHash": "0x1", "logIndex": "0x0"},
        {"topics": ["0xV2OF"], "transactionHash": "0x2", "logIndex": "0x0"},
        {"topics": ["0xOTHER"], "transactionHash": "0x3", "logIndex": "0x0"},
    ]
    hist = fwh.topic0_histogram(logs)
    assert hist == {"0xv2of": 2, "0xother": 1}


def test_fetch_one_wallet_runs_maker_and_taker_passes(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_get_logs(rpc_url, address, from_block, to_block, topics=None):
        calls.append((address, tuple(topics) if topics else None))
        # Return one synthetic log keyed by the topic filter so merge dedups correctly.
        wallet_topic = topics[2] if topics and len(topics) > 2 and topics[2] else topics[3]
        return [{"topics": ["0xV2OF", "0xoh", wallet_topic or "0x", "0x"],
                 "transactionHash": "0x" + address[-2:], "logIndex": "0x0"}]

    monkeypatch.setattr(fwh, "_rpc_get_logs", fake_get_logs)
    out = fwh.fetch_one_wallet(
        "0x" + "11" * 20, rpc_url="http://x", from_block=0, to_block=10,
        exchanges_topic0=[("0xExch", "0xV2OF")],
    )
    # one exchange * (maker pass + taker pass) = 2 calls
    assert len(calls) == 2
    assert len(out) >= 1


def test_v1_fraction_for_wallet_median_based() -> None:
    # Verify v1_fraction_for_wallet computes per-wallet fraction correctly.
    # V2 topic0 lowercased
    v2_t = fwh.V2_TOPIC0.lower()
    # All V2 -> fraction 0.0
    hist_all_v2 = {v2_t: 10}
    assert fwh.v1_fraction_for_wallet(hist_all_v2) == 0.0
    # Half V1-or-other -> fraction 0.5
    hist_half = {v2_t: 5, "0xother": 5}
    assert fwh.v1_fraction_for_wallet(hist_half) == 0.5
    # Empty -> None (no logs)
    assert fwh.v1_fraction_for_wallet({}) is None
