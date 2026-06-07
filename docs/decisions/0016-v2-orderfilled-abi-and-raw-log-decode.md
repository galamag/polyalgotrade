# ADR 0016 — V2 OrderFilled ABI, raw-log decode recipe, and parser field-name bridge

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** AI engineer (claims-verifier, I8 verification against primary sources)

## Context

Claim I8 in `docs/research/claims-verification.md` was PENDING: we had asserted (but never
verified) that the V2 CTF Exchange `OrderFilled` event carries maker/taker addresses, which
would enable copy-trading attribution (C1). Separately, `src/pat/data/polymarket_history.py`
was written against a pre-verification field schema using `makerAssetId`/`takerAssetId` key
names. Those names come from V1 — we needed to confirm whether they survive in V2.

Verification was done against:
- Polygonscan verified ABI for `0xE111180000d2663C0091e4f400237545B87B996B`
- GitHub `Polymarket/ctf-exchange-v2` `src/exchange/interfaces/ITrading.sol` and `src/exchange/mixins/Events.sol`
- Live on-chain tx `0x5f58d002310ce745cc80c7bcbc822cd7adce5d6f4a429d67064300715d583c21`,
  Polygon block 88093791, checked 2026-06-07

## Decision

### 1. Canonical V2 OrderFilled event

```
event OrderFilled(
    bytes32 indexed orderHash,
    address indexed maker,
    address indexed taker,
    uint8           side,
    uint256         tokenId,
    uint256         makerAmountFilled,
    uint256         takerAmountFilled,
    uint256         fee,
    bytes32         builder,
    bytes32         metadata
)
```

topic0: `0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee`
(keccak256 of `OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)`)

### 2. Raw log layout

```
topics[0]  fixed selector (topic0 above)
topics[1]  bytes32  orderHash        (indexed)
topics[2]  address  maker            (indexed, left-padded to 32 bytes)
topics[3]  address  taker            (indexed, left-padded to 32 bytes)
data       7 x 32-byte ABI words:
  [0]  uint8   side               0 = BUY, 1 = SELL
  [1]  uint256 tokenId            ERC-1155 position ID (shares leg)
  [2]  uint256 makerAmountFilled  6-dp fixed-point
  [3]  uint256 takerAmountFilled  6-dp fixed-point
  [4]  uint256 fee                6-dp fixed-point
  [5]  bytes32 builder            usually 0x0
  [6]  bytes32 metadata           usually 0x0
```

### 3. Decode recipe (Python)

```python
def decode_v2_orderfilled(log: dict) -> dict:
    """
    Decode a raw eth_getLogs response entry for the V2 OrderFilled event
    into the dict schema expected by parse_orderfilled() in polymarket_history.py.
    block_timestamps: dict[int, int]  — blockNumber -> Unix epoch seconds,
                      pre-fetched via eth_getBlockByNumber.
    """
    order_hash = log["topics"][1]
    maker_addr = "0x" + log["topics"][2][-40:]
    taker_addr = "0x" + log["topics"][3][-40:]

    data = bytes.fromhex(log["data"].lstrip("0x"))
    words = [int.from_bytes(data[i:i+32], "big") for i in range(0, 224, 32)]
    side, token_id, maker_amt, taker_amt, fee, builder, metadata = words

    # Bridge V2 (side+tokenId) to V1-style (makerAssetId/takerAssetId)
    # so parse_orderfilled() works without modification.
    # side=0 (BUY):  maker gives USDC (assetId "0"), taker gives shares
    # side=1 (SELL): maker gives shares, taker gives USDC (assetId "0")
    if side == 0:
        maker_asset_id, taker_asset_id = "0", str(token_id)
    else:
        maker_asset_id, taker_asset_id = str(token_id), "0"

    block_number = int(log["blockNumber"], 16)
    # Caller must provide block_timestamp (epoch seconds); multiply by 1000 for ms.
    # See timestamp note below.

    return {
        "orderHash":         order_hash,
        "maker":             maker_addr,
        "taker":             taker_addr,
        "side":              side,
        "tokenId":           str(token_id),
        "makerAssetId":      maker_asset_id,    # bridge field
        "takerAssetId":      taker_asset_id,    # bridge field
        "makerAmountFilled": maker_amt,
        "takerAmountFilled": taker_amt,
        "fee":               fee,
        "builder":           hex(builder),
        "metadata":          hex(metadata),
        "blockNumber":       block_number,
        "transactionHash":   log["transactionHash"],
        # timestamp: filled by caller after eth_getBlockByNumber lookup
    }
```

### 4. Timestamp strategy

`eth_getLogs` does NOT return timestamps. The standard approach is:

```
eth_getBlockByNumber(blockNumber, false) -> result.timestamp  (hex, Unix epoch seconds)
```

Multiply by 1000 for epoch milliseconds (parser expectation).

**Optimization:** deduplicate by block number. Polygon is ~2s/block; a batch of 1000 events
typically spans O(10)–O(100) unique blocks. Cache `{blockNumber: timestamp}` within a batch.
Alchemy cost: 20 CU per `eth_getBlockByNumber` call.

### 5. I8 resolution

maker address = `topics[2]` (indexed), taker address = `topics[3]` (indexed).
Copy-trading attribution (C1) is feasible: filter `eth_getLogs` by `topics[3]` to see which
maker fills a specific taker, or by `topics[2]` to follow a specific maker. I8 status: VERIFIED.

## Options considered

1. **Rewrite parser to use V2 native field names (`side`/`tokenId`)** — cleaner long-term but
   changes the existing tested interface; requires updating fixtures and tests.
2. **Add a thin adapter that bridges V2 fields to the existing V1-style dict** (chosen) —
   zero change to `polymarket_history.py`; the bridge is the right seam for the data layer.
3. **Use the `polymarket-client` SDK decode** — introduces SDK dependency into what should be
   a pure-transform parsing layer; harder to test in isolation.

## Rationale

Option 2 keeps `polymarket_history.py` a pure transform with a stable, tested interface. The
adapter (`decode_v2_orderfilled`) lives in `src/pat/data/` alongside the parser, clearly
labelled as the V2 raw-log layer. If V3 appears, only the adapter changes.

## Consequences

- Positive: parser unchanged; copy-trading attribution enabled; decode recipe fully specified.
- Negative: bridge fields (`makerAssetId`/`takerAssetId`) are synthetic — the adapter comment
  must document this to avoid confusion.
- Follow-ups:
  - Implement `decode_v2_orderfilled` in `src/pat/data/polymarket_on_chain.py` (new file).
  - Add `eth_getBlockByNumber` batch-fetch helper with block-level caching.
  - Phase 1 fixtures must be regenerated from real V2 log data (not V1 field names).
  - Consider whether `tokenId` should be added as a first-class field on `Fill` (currently
    derived via the asset-ID bridge — works but is indirect).
