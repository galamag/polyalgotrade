"""V2 CTF Exchange raw-log layer: decode OrderFilled logs + enrich with block timestamps.

ADR 0016 specifies the decode recipe. This module bridges raw eth_getLogs entries
(V2: side + tokenId) to the V1-style dict (makerAssetId / takerAssetId) that the pure
parser `pat.data.polymarket_history.parse_orderfilled` already consumes — so the parser
stays unchanged. No web3/eth-abi dependency: hand-rolled bytes.fromhex + int.from_bytes.

Network isolation: the ONLY function that touches the wire is `_rpc_get_block_timestamp`
(added in a later task). Monkeypatch it (or pass `get_ts=`) in tests.
"""

from __future__ import annotations

from typing import Any

import structlog

# keccak256("OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,"
#           "bytes32,bytes32)")
TOPIC0_ORDERFILLED = (
    "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
)

_DATA_WORDS = 7  # side, tokenId, makerAmt, takerAmt, fee, builder, metadata

log = structlog.get_logger(__name__)


def decode_v2_orderfilled(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Decode one raw eth_getLogs entry into the dict `parse_orderfilled` expects.

    Returns None if the log is not an OrderFilled event (topics[0] mismatch).
    The returned dict carries the parser's required keys plus extras (maker/taker/
    side/tokenId/blockNumber) preserved for future copy-trading. `timestamp` is NOT
    set here — a later enrichment step injects it.
    """
    topics = raw["topics"]
    if topics[0].lower() != TOPIC0_ORDERFILLED:
        return None

    maker_addr = "0x" + topics[2][-40:]
    taker_addr = "0x" + topics[3][-40:]

    data_hex = raw["data"]
    if data_hex.startswith("0x"):
        data_hex = data_hex[2:]  # NB: do NOT use lstrip("0x") — it strips leading data zeros
    data = bytes.fromhex(data_hex)
    if len(data) < _DATA_WORDS * 32:
        raise ValueError(
            f"OrderFilled data too short: {len(data)} bytes, need {_DATA_WORDS * 32}"
        )
    words = [
        int.from_bytes(data[i : i + 32], "big")
        for i in range(0, _DATA_WORDS * 32, 32)
    ]
    side, token_id, maker_amt, taker_amt, fee, builder, metadata = words

    # Bridge V2 (side+tokenId) -> V1-style makerAssetId/takerAssetId ("0" = USDC collateral leg).
    if side == 0:  # BUY: maker gives USDC, taker gives shares
        maker_asset_id, taker_asset_id = "0", str(token_id)
    else:  # SELL: maker gives shares, taker gives USDC
        maker_asset_id, taker_asset_id = str(token_id), "0"

    return {
        "makerAssetId": maker_asset_id,
        "takerAssetId": taker_asset_id,
        "makerAmountFilled": maker_amt,
        "takerAmountFilled": taker_amt,
        "fee": fee,
        "transactionHash": raw["transactionHash"],
        # extras (not read by the parser; preserved for copy-trading / provenance)
        "orderHash": topics[1],
        "maker": maker_addr,
        "taker": taker_addr,
        "side": side,
        "tokenId": str(token_id),
        "builder": hex(builder),
        "metadata": hex(metadata),
        "blockNumber": int(raw["blockNumber"], 16),
    }
