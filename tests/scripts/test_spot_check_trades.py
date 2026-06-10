"""Offline tests for scripts/spot_check_trades.py — fixture receipts, no network."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "spot_check_trades",
    Path(__file__).resolve().parents[2] / "scripts" / "spot_check_trades.py",
)
assert _SPEC and _SPEC.loader
sct = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sct)

from pat.data.polymarket_on_chain import TOPIC0_ORDERFILLED  # noqa: E402

_WALLET = "0x" + "ab" * 20
_OTHER = "0x" + "cd" * 20


def _word(v: int) -> str:
    return f"{v:064x}"


def _addr_topic(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:]


def _receipt(tx: str, *, side: int, token_id: int, maker_amt: int, taker_amt: int,
             maker: str, taker: str) -> dict:
    data = "0x" + _word(side) + _word(token_id) + _word(maker_amt) + _word(taker_amt) \
        + _word(0) + _word(0) + _word(0)
    return {"logs": [{
        "topics": [TOPIC0_ORDERFILLED, "0x" + "11" * 32,
                   _addr_topic(maker), _addr_topic(taker)],
        "data": data,
        "transactionHash": tx,
        "blockNumber": "0x10",
    }]}


def _trade(tx: str, *, side: str = "BUY", price: str = "0.4", size: str = "10",
           ts: int = 100) -> dict:
    return {"transactionHash": tx, "asset": "777", "side": side, "price": price,
            "size": size, "timestamp": ts}


def test_matching_taker_buy_counts_as_match() -> None:
    # wallet is TAKER and BUYS 10 @ 0.4 -> on-chain order side=1 (maker SELLS),
    # maker_amt = shares (10e6), taker_amt = USDC (4e6)
    receipts = {"0xt1": _receipt("0xt1", side=1, token_id=777, maker_amt=10_000_000,
                                 taker_amt=4_000_000, maker=_OTHER, taker=_WALLET)}
    res = sct.check_wallet(
        _WALLET, [_trade("0xt1")], "http://rpc",
        get_receipt=lambda _u, h: receipts[h],
    )
    assert res["n_checked"] == 1
    assert res["n_matched"] == 1
    assert res["mismatches"] == []


def test_size_mismatch_is_recorded() -> None:
    receipts = {"0xt1": _receipt("0xt1", side=1, token_id=777, maker_amt=9_000_000,
                                 taker_amt=4_000_000, maker=_OTHER, taker=_WALLET)}
    res = sct.check_wallet(
        _WALLET, [_trade("0xt1")], "http://rpc",
        get_receipt=lambda _u, h: receipts[h],
    )
    assert res["n_matched"] == 0
    assert len(res["mismatches"]) == 1


def test_receipt_cap_limits_lookups() -> None:
    calls: list[str] = []

    def fake(_u: str, h: str) -> dict:
        calls.append(h)
        return _receipt(h, side=1, token_id=777, maker_amt=10_000_000,
                        taker_amt=4_000_000, maker=_OTHER, taker=_WALLET)

    trades = [_trade(f"0xt{i}", ts=i) for i in range(60)]
    res = sct.check_wallet(_WALLET, trades, "http://rpc", n_sample=60, get_receipt=fake)
    assert len(calls) <= sct._MAX_RECEIPTS
    assert res["n_checked"] <= sct._MAX_RECEIPTS
