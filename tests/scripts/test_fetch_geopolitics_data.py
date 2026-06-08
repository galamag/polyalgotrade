from __future__ import annotations

import json

import httpx


def _raw_log(
    token_id: str, *, side: int = 0, maker_amt: int = 2_500_000,
    taker_amt: int = 5_000_000, fee: int = 0, tx: str = "0xtx", block: str = "0x64",
) -> dict:
    from tests.data.test_polymarket_on_chain import _make_raw_log

    return _make_raw_log(side=side, token_id=int(token_id), maker_amt=maker_amt,
                         taker_amt=taker_amt, fee=fee, tx=tx, block=block)


def _patch_all_seams(monkeypatch, *, geo_token: str, other_token: str, ts_calls: list[int]) -> None:
    from pat.data import polymarket_on_chain as oc
    from pat.venues.polymarket import gamma
    from scripts import fetch_geopolitics_data as g

    # Gamma: one 0%-fee market (geo_token) + one fee-bearing market (other_token).
    monkeypatch.setattr(
        gamma, "_gamma_get_events",
        lambda *a, **k: [{"markets": [
            {"feesEnabled": False, "clobTokenIds": [geo_token]},
            {"feesEnabled": True, "clobTokenIds": [other_token]},
        ]}],
    )
    # Logs: one geo fill + one non-geo fill (different blocks).
    monkeypatch.setattr(
        g, "fetch_orderfilled_logs",
        lambda *a, **k: [_raw_log(geo_token, block="0x64"), _raw_log(other_token, block="0xC8")],
    )

    def fake_ts(rpc_url, block_number):
        ts_calls.append(block_number)
        return 1_700_000_000 + block_number

    monkeypatch.setattr(oc, "_rpc_get_block_timestamp", fake_ts)


def test_orchestration_writes_geo_only_with_timestamps(monkeypatch, tmp_path) -> None:
    from scripts import fetch_geopolitics_data as g

    geo, other = "111", "999"
    ts_calls: list[int] = []
    _patch_all_seams(monkeypatch, geo_token=geo, other_token=other, ts_calls=ts_calls)

    out_path = g.run(out_dir=tmp_path, from_block=1, to_block=300, rpc_url="rpc")
    written = json.loads(out_path.read_text(encoding="utf-8"))

    assert len(written) == 1                      # only the geo fill survives the filter
    assert written[0]["tokenId"] == geo
    assert written[0]["timestamp"] == (1_700_000_000 + 100) * 1000
    assert "maker" in written[0] and "taker" in written[0]   # preserved for copy-trading
    # timestamps fetched ONLY for the geo block (CU saving)
    assert ts_calls == [100]


def test_orchestration_no_real_network(monkeypatch, tmp_path) -> None:
    from scripts import fetch_geopolitics_data as g

    ts_calls: list[int] = []
    _patch_all_seams(monkeypatch, geo_token="111", other_token="999", ts_calls=ts_calls)

    def _boom(*a, **k):
        raise AssertionError("Real network call detected")

    monkeypatch.setattr(httpx, "Client", _boom)
    g.run(out_dir=tmp_path, from_block=1, to_block=300, rpc_url="rpc")  # must not raise


def test_orchestration_fast_ts_uses_block_number_and_skips_rpc(monkeypatch, tmp_path) -> None:
    from scripts import fetch_geopolitics_data as g

    geo, other = "111", "999"
    ts_calls: list[int] = []
    _patch_all_seams(monkeypatch, geo_token=geo, other_token=other, ts_calls=ts_calls)

    out_path = g.run(out_dir=tmp_path, from_block=1, to_block=300, rpc_url="rpc", fast_ts=True)
    written = json.loads(out_path.read_text(encoding="utf-8"))

    assert len(written) == 1
    assert written[0]["tokenId"] == geo
    assert written[0]["timestamp"] == 100 * 1000   # geo block 0x64=100 -> ts=block*1000
    assert ts_calls == []                           # fast mode makes NO eth_getBlockByNumber call
