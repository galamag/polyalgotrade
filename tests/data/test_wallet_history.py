from __future__ import annotations

from pat.data.wallet_history import merge_maker_taker, wallet_to_topic


def test_wallet_to_topic_left_pads_to_32_bytes_lowercase() -> None:
    addr = "0x2CFF41636FE21FAD120FED603D54D4FDD96259DB"
    assert wallet_to_topic(addr) == "0x" + "0" * 24 + "2cff41636fe21fad120fed603d54d4fdd96259db"


def test_merge_maker_taker_dedups_by_tx_and_logindex() -> None:
    a = {"transactionHash": "0xaa", "logIndex": "0x1", "data": "m"}
    b = {"transactionHash": "0xaa", "logIndex": "0x2", "data": "t"}
    dup = {"transactionHash": "0xaa", "logIndex": "0x1", "data": "m"}  # same key as a
    merged = merge_maker_taker([a], [b, dup])
    # a and b survive (distinct keys); dup of a is dropped
    keys = {(e["transactionHash"], e["logIndex"]) for e in merged}
    assert keys == {("0xaa", "0x1"), ("0xaa", "0x2")}
    assert len(merged) == 2
