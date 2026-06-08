"""Tests for scripts/fetch_polymarket_history.py — no real network calls.

The _rpc_get_logs function is the single network seam; everything else is
tested by monkeypatching it with a static fixture list.
"""

from __future__ import annotations


def test_fetch_writes_raw(monkeypatch, tmp_path):
    from scripts import fetch_polymarket_history as f

    monkeypatch.setattr(
        f,
        "_rpc_get_logs",
        lambda *a, **k: [
            {
                "timestamp": 1,
                "makerAmountFilled": "1000000",
                "takerAmountFilled": "2500000",
                "makerAssetId": "1",
                "transactionHash": "0xabc",
            }
        ],
    )
    out = f.run(out_dir=tmp_path, from_block=1, to_block=2)
    assert out.exists()


def test_fetch_filename_matches_blocks(monkeypatch, tmp_path):
    """The output filename encodes the queried block range for easy resumability."""
    from scripts import fetch_polymarket_history as f

    monkeypatch.setattr(f, "_rpc_get_logs", lambda *a, **k: [])
    out = f.run(out_dir=tmp_path, from_block=100, to_block=200)
    assert out.name == "orderfilled_100_200.json"


def test_fetch_json_content(monkeypatch, tmp_path):
    """The raw log list is written verbatim to the JSON file."""
    import json

    from scripts import fetch_polymarket_history as f

    fake_log = {
        "timestamp": 999,
        "makerAmountFilled": "500000",
        "takerAmountFilled": "1000000",
        "makerAssetId": "42",
        "transactionHash": "0xdeadbeef",
    }
    monkeypatch.setattr(f, "_rpc_get_logs", lambda *a, **k: [fake_log])
    out = f.run(out_dir=tmp_path, from_block=10, to_block=20)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["transactionHash"] == "0xdeadbeef"


def test_no_real_network(monkeypatch, tmp_path):
    """Confirm that httpx is never called when _rpc_get_logs is patched.

    We patch httpx.Client to raise if instantiated; if the mock is
    correctly intercepted, httpx is never reached.
    """
    import httpx

    from scripts import fetch_polymarket_history as f

    def _boom(*args, **kwargs):
        raise AssertionError("Real network call detected — httpx.Client should not be reached")

    monkeypatch.setattr(httpx, "Client", _boom)
    monkeypatch.setattr(f, "_rpc_get_logs", lambda *a, **k: [])
    # Should not raise.
    f.run(out_dir=tmp_path, from_block=1, to_block=1)


def test_build_getlogs_payload_includes_topics() -> None:
    from scripts.fetch_polymarket_history import _build_getlogs_payload

    payload = _build_getlogs_payload("0xADDR", 10, 20, topics=["0xTOPIC"])
    params = payload["params"][0]
    assert params["address"] == "0xADDR"
    assert params["fromBlock"] == hex(10)
    assert params["toBlock"] == hex(20)
    assert params["topics"] == ["0xTOPIC"]


def test_build_getlogs_payload_omits_topics_when_none() -> None:
    from scripts.fetch_polymarket_history import _build_getlogs_payload

    payload = _build_getlogs_payload("0xADDR", 10, 20, topics=None)
    assert "topics" not in payload["params"][0]


def test_fetch_orderfilled_logs_queries_all_addresses(monkeypatch) -> None:
    from scripts import fetch_polymarket_history as f

    seen: list[str] = []

    def fake_get_logs(rpc_url, address, from_block, to_block, topics=None):
        seen.append(address)
        return [{"address": address}]

    monkeypatch.setattr(f, "_rpc_get_logs", fake_get_logs)
    out = f.fetch_orderfilled_logs("rpc", [f.EXCHANGE_V2, f.NEGRISK_V2], 1, 2)
    assert seen == [f.EXCHANGE_V2, f.NEGRISK_V2]
    assert len(out) == 2
