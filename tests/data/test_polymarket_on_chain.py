from __future__ import annotations

from decimal import Decimal

import httpx

from pat.data.polymarket_history import parse_orderfilled
from pat.data.polymarket_on_chain import TOPIC0_ORDERFILLED, decode_v2_orderfilled

# A real geopolitics-shaped ERC-1155 token id (decimal string), reused from the V1 fixture.
TOKEN = "71321045679252212594626385532706912750332728571942532289631379312455583992616"


def _make_raw_log(
    *,
    side: int,
    token_id: int,
    maker_amt: int,
    taker_amt: int,
    fee: int,
    tx: str = "0xtx",
    block: str = "0x539",  # 1337
    maker: str = "0x" + "11" * 20,
    taker: str = "0x" + "22" * 20,
    topic0: str = TOPIC0_ORDERFILLED,
) -> dict:
    """Build a synthetic raw eth_getLogs entry with known field values."""
    words = [side, token_id, maker_amt, taker_amt, fee, 0, 0]
    data = "0x" + "".join(f"{w:064x}" for w in words)

    def _pad(addr: str) -> str:
        return "0x" + addr.lower().removeprefix("0x").rjust(64, "0")

    return {
        "topics": [topic0, "0x" + "ab" * 32, _pad(maker), _pad(taker)],
        "data": data,
        "blockNumber": block,
        "transactionHash": tx,
    }


def test_decode_buy_bridges_to_usdc_maker_leg() -> None:
    # side=0 (BUY): maker gives USDC ("0"), taker gives shares. USDC 2.5 / shares 5 -> price 0.5.
    log = _make_raw_log(
        side=0, token_id=int(TOKEN), maker_amt=2_500_000, taker_amt=5_000_000, fee=25_000
    )
    dec = decode_v2_orderfilled(log)
    assert dec is not None
    assert dec["makerAssetId"] == "0"
    assert dec["takerAssetId"] == TOKEN
    assert dec["makerAmountFilled"] == 2_500_000
    assert dec["takerAmountFilled"] == 5_000_000
    assert dec["fee"] == 25_000
    assert dec["tokenId"] == TOKEN
    assert dec["side"] == 0
    assert dec["blockNumber"] == 1337
    assert dec["transactionHash"] == "0xtx"
    # maker/taker preserved for future copy-trading (decision 3 in the spec)
    assert dec["maker"] == "0x" + "11" * 20
    assert dec["taker"] == "0x" + "22" * 20


def test_decode_sell_bridges_to_shares_maker_leg() -> None:
    # side=1 (SELL): maker gives shares, taker gives USDC. shares 5 / USDC 2.5 -> price 0.5.
    log = _make_raw_log(
        side=1, token_id=int(TOKEN), maker_amt=5_000_000, taker_amt=2_500_000, fee=0
    )
    dec = decode_v2_orderfilled(log)
    assert dec is not None
    assert dec["makerAssetId"] == TOKEN
    assert dec["takerAssetId"] == "0"


def test_decode_feeds_parser_to_correct_fill() -> None:
    # End-to-end: decode -> parse_orderfilled yields the expected Fill (price 0.5, size 5).
    log = _make_raw_log(
        side=0, token_id=int(TOKEN), maker_amt=2_500_000, taker_amt=5_000_000, fee=25_000
    )
    dec = decode_v2_orderfilled(log)
    assert dec is not None
    dec["timestamp"] = 1_717_200_000_000  # normally injected by enrich_timestamps
    fill = parse_orderfilled([dec])[0]
    assert fill.price == Decimal("0.5")
    assert fill.size == Decimal("5")
    assert fill.fee == Decimal("0.025")
    assert fill.token_id == TOKEN


def test_decode_skips_non_orderfilled_topic() -> None:
    log = _make_raw_log(
        side=0, token_id=int(TOKEN), maker_amt=1, taker_amt=2, fee=0, topic0="0xdeadbeef"
    )
    assert decode_v2_orderfilled(log) is None


def test_decode_raises_on_short_data() -> None:
    import pytest

    log = _make_raw_log(side=0, token_id=1, maker_amt=1, taker_amt=1, fee=0)
    log["data"] = "0x" + "00" * 32  # only 1 word present, decoder needs 7
    with pytest.raises(ValueError):
        decode_v2_orderfilled(log)


def test_enrich_timestamps_dedups_blocks_and_scales_to_ms() -> None:
    from pat.data import polymarket_on_chain as oc

    calls: list[int] = []

    def fake_get_ts(rpc_url: str, block_number: int) -> int:
        calls.append(block_number)
        return 1_700_000_000 + block_number  # epoch SECONDS

    events = [
        {"blockNumber": 100, "transactionHash": "0xa"},
        {"blockNumber": 100, "transactionHash": "0xb"},  # same block -> no extra RPC call
        {"blockNumber": 200, "transactionHash": "0xc"},
    ]
    out = oc.enrich_timestamps(events, rpc_url="x", get_ts=fake_get_ts)

    assert calls == [100, 200]  # deduped, first-seen order
    assert out[0]["timestamp"] == (1_700_000_000 + 100) * 1000  # seconds -> ms
    assert out[1]["timestamp"] == (1_700_000_000 + 100) * 1000
    assert out[2]["timestamp"] == (1_700_000_000 + 200) * 1000


def test_enrich_timestamps_no_real_network(monkeypatch) -> None:
    from pat.data import polymarket_on_chain as oc

    def _boom(*a, **k):
        raise AssertionError("Real network call detected")

    monkeypatch.setattr(httpx, "Client", _boom)
    events = [{"blockNumber": 1, "transactionHash": "0xa"}]
    out = oc.enrich_timestamps(
        events, rpc_url="x", get_ts=lambda rpc_url, block_number: 1_700_000_000
    )
    assert out[0]["timestamp"] == 1_700_000_000 * 1000
