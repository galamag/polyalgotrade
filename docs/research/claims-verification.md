# Claims Verification

The source research (`2026-06-07-original-research.md`) is **second-hand**. We build on a claim
only after a **primary source** confirms it (`CLAUDE.md` §1.2).

**Status legend:** `VERIFIED` · `REFUTED` · `PARTIAL` (core true, details off) · `STALE`
(was true, recheck) · `CANNOT_CONFIRM` · `PENDING`.

**Phase 0 verified the Critical block (C1–C9) on 2026-06-07** via the `claims-verifier`
subagent against official docs / GitHub / PyPI / Polygonscan. Detailed findings + sources are
in the section below the tables. **Gate result: no Critical claim is `PENDING` → Phase 1
unblocked**, with the corrections noted.

> ⚠️ Latency numbers and bot-P&L figures from the research come from blogs/VPS vendors —
> low-trust, measure ourselves (L1–L3, still PENDING).

---

## Critical (gate Phase 1)

| # | Claim (research) | Status | One-line finding | Primary source |
|---|---|---|---|---|
| C1 | V2 live 2026-04-28; exchange `0xE111…996B`, neg-risk `0xe2222…0F59`; old `0x4bFb…982E` disabled | **PARTIAL** | Addresses ✅ real/active; launch ❌ ~Mar 31/Apr 3; old V1 ❌ still live (not disabled) | docs.polymarket.com/resources/contracts; github Polymarket/ctf-exchange-v2; polygonscan |
| C2 | Collateral pUSD (ERC-20, 1:1 USDC) on Polygon | **PARTIAL** | ✅ pUSD real (`0xC011…2DFB`), backed by **USDC.e**; needs USDC.e→pUSD onramp step | docs.polymarket.com/concepts/pusd |
| C3 | Order dropped nonce/feeRateBps/taker; added timestamp/metadata/builder; EIP-712 ver "2" | **PARTIAL** | ✅ ver "2" + full struct confirmed; research field list **incomplete** (omits salt/signer/signatureType) | github ctf-exchange-v2 Structs.sol / Hashing.sol |
| C4 | SDK `py-clob-client-v2` v1.0.1+; old client dead | **PARTIAL** | py-clob-client-v2 exists but **superseded**; use unified **`polymarket-client`** (py-sdk) | pypi.org; github Polymarket/py-sdk; docs.polymarket.com/dev-tooling/python |
| C5 | Crypto taker `C·0.07·p·(1−p)`; peak 1.56–1.80% | **PARTIAL** | ✅ formula + 0.07; peak is **exactly 1.75%** at p=0.5 (range was wrong); full category table obtained | docs.polymarket.com/trading/fees |
| C6 | Geopolitics taker fee = 0% | **VERIFIED** | ✅ "Geopolitical and world events markets are fee-free"; **maker rebate also 0** there | docs.polymarket.com/trading/fees |
| C7 | Maker rebates 25% (20% crypto), daily pUSD, $1 min | **VERIFIED** | ✅ all three confirmed; model as **daily batch credit**, $1/day gate matters on small bankroll | docs.polymarket.com/market-makers/maker-rebates |
| C8 | Kalshi `round(0.07·p·(1−p),2)`/contract; maker $0 | **PARTIAL** | ✅ 0.07 + shape; ❌ rounding is **CEIL** to $0.0001; ❌ maker fee **0.0175** (not $0) | kalshi fee schedule; docs.kalshi.com/getting_started/fee_rounding |
| C9 | KZ not blocked on Polymarket (33) or Kalshi (~52) | **VERIFIED** | ✅ KZ absent from both lists (PM 33 @2026-04-23; Kalshi 54 @2025-10-23). Mutable — recheck pre-Phase-5 | help.polymarket.com geographic-restrictions; Kalshi member-agreement notice |

## Important (Phase 1–3)

| # | Claim | Status | One-line finding | Source |
|---|---|---|---|---|
| I1 | CLOB endpoints (4 URLs) | **PARTIAL** | ✅ 4 URLs correct but **incomplete** — also need `/ws/user`, `data-api.polymarket.com` | docs.polymarket.com/api-reference/introduction; asyncapi.json |
| I2 | Rate limits 120k/10min; 2000/10s | **PARTIAL** | ✅ confirmed + extra tiers (burst 5000/10s; batch 21000/10min); Cloudflare queues | docs.polymarket.com/api-reference/rate-limits |
| I3 | `warproxxx/poly_data` reads OrderFilled from V2 via RPC+Gamma | **VERIFIED** | ✅ exists; targets `0xE111…996B`; Gamma keyset; off Goldsky; use paid RPC | github.com/warproxxx/poly_data |
| I4 | Kalshi `demo-api.kalshi.com` full sandbox | **PARTIAL** | ✅ fake-money sandbox; ❌ host is **`.co`**: `external-api.demo.kalshi.co/trade-api/v2` | docs.kalshi.com/getting_started/demo_env |
| I5 | 15-min/1-hr crypto auto-settle via Chainlink | **PARTIAL** | ✅ two-tier: **Chainlink** resolves short crypto (no UMA dispute); **UMA** for the rest. Adapter addr not in docs — trace on-chain when needed | Polymarket↔Chainlink partnership PR; docs.polymarket.com/concepts/resolution |
| I6 | Polymarket KYC optional ≤7-figure | **VERIFIED** | ✅ User (KZ): site opens no-VPN, **no KYC** at deposit; account is **email/Gmail embedded wallet** (not MetaMask) — see ADR 0011 | user test 2026-06-07 |
| I7 | Polygon base fee ≥25 gwei; tx ≈ $0.0024 | **PARTIAL** | ✅ gas negligible (~$0.002–0.005); ❌ no confirmed 25-gwei floor — fetch gas live | polygonscan.com/gastracker |
| I8 | V2 `OrderFilled` event carries maker/taker **addresses** (would enable C1 copy-trading attribution) | **VERIFIED** | ✅ maker (topic2) + taker (topic3) are indexed addresses. ⚠️ V2 event schema differs from V1: has `side`+`tokenId` (NOT `makerAssetId`/`takerAssetId`). Parser needs a raw-log→dict adapter. See ADR 0016. | Polygonscan ABI + GitHub ITrading.sol; live tx 0x5f58d002…c21 on Polygon block 88093791 (2026-06-07) |
| I9 | Gamma: select geopolitics markets + token_ids; "geopolitics = 0% fee" nuance | **VERIFIED** | ✅ `/events?tag_id=100265` → `markets[].clobTokenIds` (YES/NO). ⚠️ **tag ≠ 0% fee**: select 0%-fee by `feesEnabled=false`/`feeType=null` per market (some geopolitics-tagged markets carry politics_fees 4%). Per-token: `clob.polymarket.com/fee-rate?token_id=`. ~35–40 events. | live gamma-api + clob /fee-rate (2026-06-07); docs gamma-openapi |
| I10 | NegRisk CTF Exchange (`0xe2222…0F59`) emits **identical** `OrderFilled` event (same topic0, same non-indexed data layout) as main exchange — decoder works unchanged | **VERIFIED** | ✅ NegRisk deploys the SAME `CTFExchange` contract (confirmed Polygonscan source). `Events.sol` `_ORDER_FILLED_TOPIC` = `keccak256("OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)")` ≡ `0xd543adfd...d8ee`. Live tx `0xcc667e6a…e3968` on NegRisk contract shows topic0 = `0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee` with 7-word data layout (side,tokenId,makerAmountFilled,takerAmountFilled,fee,builder,metadata) byte-for-byte identical. ⚠️ The `INegRiskAdapter` emits additional NegRisk-only events (PositionsConverted, MarketPrepared, etc.) on its own adapter contract — irrelevant to OrderFilled decode. | GitHub raw `Events.sol` + `ITrading.sol` (ctf-exchange-v2 main); Polygonscan `0xe2222…0F59` verified source; live tx `0xcc667e6a64a151718069671341b33335dab5e05cb669f26baae35270b24e3968` (Polygon, 2026-06-08) |

## Low-trust / measure-ourselves

| # | Claim | Status | Note |
|---|---|---|---|
| L1 | Latency Dublin <5ms … Helsinki ~25–30ms | **PENDING** | Measure with `ping`/`mtr` from a real VPS (deferred to VPS setup) |
| L2 | Stats: 0.51% wallets >$1k; spreads 4.5%→1.2%; 2.7s window | **PENDING** | Directional only; don't build on exact numbers |
| L3 | Bot P&L ($313→$437K etc.) | **PENDING** | Survivorship bias; informative only |

## Compliance / personal

| # | Claim | Status | Note |
|---|---|---|---|
| P1 | KZ crypto income taxable 10% IIT | **VERIFIED** | User (resident): 10% ИПН, declared as **property income** (имущественный доход); crypto not eligible for simplified regime. Keep fill records |
| P2 | Off-ramp USDC→Binance→P2P ~1–2% | **VERIFIED** | ✅ Better: **Freedom Bank↔Binance KZ** direct gateway, USDT ~1:1 (~485 KZT), **no fee** both ways; only real cost = on-chain transfer fee |

---

## Phase 0 detailed findings (checked 2026-06-07)

### C1 — V2 contracts (PARTIAL)
- **Addresses VERIFIED:** `0xE111180000d2663C0091e4f400237545B87B996B` (CTFExchangeV2) and
  `0xe2222d279d744050d28e00520010520000310F59` (NegRiskCtfExchangeV2) are deployed, verified,
  actively trading on Polygon (74.7M / 14.9M txns). Listed on the official contracts page + V2
  README.
- **Launch date REFUTED:** Polygonscan shows deploy ~**2026-03-31** (exchange) / **2026-04-03**
  (neg-risk), not 2026-04-28. → recalibrate any "post-V2" data window to ~late March.
- **"Old exchange disabled" REFUTED:** V1 `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` is
  **not paused** and still had txns on 2026-06-07; the V1 *repo* was archived 2026-05-11, but
  the contract is live. → Code must target V2 explicitly; never assume V1 is dead.

### C2 — pUSD (PARTIAL → core VERIFIED)
- pUSD is a real ERC-20 (proxy `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`), backed by
  **USDC.e** (bridged), 1:1, enforced on-chain via onramp/offramp (`0x93070a847efEf7…5B8ee`).
- **Impact:** funding path must wrap USDC.e→pUSD (extra step + gas); pUSD ≠ raw USDC in code.

### C3 — Order struct & EIP-712 (PARTIAL → core VERIFIED)
- Domain version `"2"` confirmed (`Hashing.sol`). Actual V2 `Order`:
  `salt, maker, signer, tokenId, makerAmount, takerAmount, side, signatureType, timestamp,
  metadata, builder, signature`. `feeRateBps`/`nonce`/`taker` indeed gone (nonce → hash-based
  OrderStatus; fee applied at match, not per-order).
- **Impact (signing is critical):** build the signer on the **exact** struct above — the
  research's "added fields" list omitted `salt/signer/signatureType` which ARE required.

### C4 — Python SDK (PARTIAL → use a different package)
- `py-clob-client` = **archived/non-functional** (migrate notice). `py-clob-client-v2`
  exists (v1.0.1, 2026-05-09) **but its own README recommends the new unified SDK**.
- **Use `polymarket-client`** (PyPI `0.1.0b3`, 2026-05-27, repo `Polymarket/py-sdk`) — what the
  official docs install. It is **beta** → pin in `uv.lock`; our thin `venues/polymarket/`
  adapter isolates beta churn. (ADR 0008.)

### C5 — Polymarket taker fee (PARTIAL → corrected)
- Formula `fee = shares · feeRate · p · (1−p)` confirmed. **Peak = exactly 1.75%** at p=0.5
  (the 1.56–1.80% range is wrong — never hard-code it; derive from the formula).
- **Category feeRate table (official):** Crypto 0.07 · Sports 0.03 · Finance 0.04 ·
  Politics 0.04 · Economics 0.05 · Culture 0.05 · Weather 0.05 · Tech 0.04 · Mentions 0.04 ·
  Other 0.05 · **Geopolitics 0.0**. Makers never charged. Rounded to 5 dp — smallest charged fee
  0.00001; smaller rounds to **zero** (corrected per Task-2 audit).
- ⚠️ **Source conflict (recheck before live):** dev-docs (5 dp, full 11-category table) vs
  help-center (4 dp; fees "rolled out sports-only effective ~2026-03-30", others listed as
  "future"). Confirm which categories are actually fee-live and 5dp-vs-4dp against the real
  Phase-2 data window before trusting non-sports fees.

### C6 — Geopolitics 0% (VERIFIED)
- Official: "Geopolitical and world events markets are fee-free." **Nuance:** the maker-rebate
  pool there is also empty → a geopolitics MM earns **pure spread**, no rebate income.

### C7 — Maker rebates (VERIFIED)
- 25% (non-crypto) / 20% (crypto) of the taker pool, **daily in pUSD**, **$1 min** (rolls
  over). Model as a **separate daily credit**, not a per-trade fee reduction. On a $50 bankroll
  the $1/day gate may rarely trigger. Separate **Taker Rebate Program** (Bronze→Obsidian)
  launched 2026-05-28 (taker-side).

### C8 — Kalshi fee (PARTIAL → corrected)
- Taker multiplier 0.07 + quadratic shape + 1.75% peak confirmed. **Corrections:** rounding is
  **CEIL** to $0.0001 (effectively to the cent for non-direct members), not `round(,2)`; **maker
  fee is 0.0175** (25% of taker), also ceil-rounded — **not $0**. Per-series `fee_multiplier`
  can override 0.07. (ADR 0009.)

### C9 — KZ access (VERIFIED, recheck-prone)
- Polymarket geographic-restrictions (updated 2026-04-23): 33 blocked countries — **KZ absent**.
- Kalshi member-agreement notice (effective 2025-10-23): 54 restricted jurisdictions — **KZ
  absent**. Both lists are explicitly mutable → **re-verify before Phase 5**.

### I1/I2 — endpoints & limits (PARTIAL, completed)
- Add to endpoint config: `wss://ws-subscriptions-clob.polymarket.com/ws/user` (fills),
  `https://data-api.polymarket.com` (positions). Rate limiter must honor burst + sustained tiers.

### I3 — data pipeline (VERIFIED)
- `warproxxx/poly_data` is a usable reference: Gamma keyset → on-chain `OrderFilled` (V2) join;
  budget a paid RPC (Alchemy/QuickNode) for throughput.

### I4 — Kalshi sandbox (PARTIAL, host corrected)
- Real demo: `https://external-api.demo.kalshi.co/trade-api/v2` (recommended) /
  `https://demo-api.kalshi.co/trade-api/v2` (legacy); WS `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`.
  Separate demo account/creds. (`.co`, not `.com`.)

### I5 — Crypto-market resolution (PARTIAL → research was right: two-tier oracle)
- **Two-tier:** short-dated crypto price markets (5-min/15-min/1-hr/4-hr) resolve via
  **Chainlink Data Streams + Automation** (on-chain, near-instant, **no UMA dispute window**);
  **all other markets** (politics, geopolitics, sports, …) resolve via **UMA Optimistic Oracle**
  (propose → 2h challenge → dispute → token vote). Confirmed by the official Polymarket↔Chainlink
  partnership announcement + the live 15M crypto category; the official contracts page lists only
  the UMA adapter/oracle, not the Chainlink resolver.
- **Design impact:** the "sell winners $0.95+, don't hold to $1.00 (UMA risk)" rule applies
  **only to UMA markets**, NOT to short-dated crypto (no dispute risk there). See ADR 0010.
- **Open (deferred, not Phase 1):** the Chainlink adapter address isn't in the docs — trace it
  on-chain (ConditionalTokens `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` `ConditionResolution`
  caller for a resolved 15-min market) when we build a resolution monitor.

### I6 — KYC (PARTIAL)
- Documented policy: **no KYC on the main platform** — wallet connect + geo-IP check only (per
  Polymarket's official 2026-05-27 statement). Perps (leveraged beta) requires KYC for testers.
  The research's "7-figure threshold" is **unverified** — drop it.
- **Impact:** no KYC docs to prepare for KZ retail onboarding on the main market. The real gate
  is the geo-IP check (C9 ✅) — the **user must test actual access from KZ** (bots are geo/login
  walled). Recheck before Phase 5.

### I7 — gas (PARTIAL)
- Negligible (~$0.002–0.005/tx) confirmed; the 25-gwei "floor" is unconfirmed (current base fee
  ~250 gwei anyway). **Fetch gas live** (`eth_feeHistory`), don't hard-code a floor.

### User onboarding facts (KZ, verified by the user 2026-06-07)
- **Access:** `polymarket.com` opens from KZ **without VPN**; **no KYC** prompt at the deposit
  button (not pursued further — re-check the full flow before funding).
- **Wallet:** account created via **Gmail/email → embedded Polymarket wallet** (NOT MetaMask/EOA).
  ⚠️ Programmatic order signing needs an EOA key (or an exportable embedded key) — see **ADR 0011**.
  Funding methods available: crypto transfer (deposit + withdraw) or **card deposit** (withdraw
  is crypto-only).
- **On-ramp cost:** card/Apple-Pay ≈ **2.18%** ($2.16 processing + $0.02 network per $100) →
  **avoid for funding**. Cheapest route: **Freedom Bank → Binance KZ** (USDT ~1:1, ~free) →
  on-chain transfer → Polymarket. Dominant cost = the crypto transfer/withdrawal fee.
- **Tax:** 10% ИПН, declared as property income.

---

### I8 — V2 OrderFilled event ABI (VERIFIED, 2026-06-07)

**Primary sources:**
- Polygonscan verified ABI for `0xE111180000d2663C0091e4f400237545B87B996B` (CTFExchangeV2)
- GitHub `Polymarket/ctf-exchange-v2` — `src/exchange/interfaces/ITrading.sol` + `src/exchange/mixins/Events.sol`
- Live on-chain tx `0x5f58d002310ce745cc80c7bcbc822cd7adce5d6f4a429d67064300715d583c21`, Polygon block 88093791
- 4byte.directory signature database confirmed topic0 mapping

**Canonical event signature (V2):**
```
OrderFilled(bytes32 indexed orderHash, address indexed maker, address indexed taker, uint8 side, uint256 tokenId, uint256 makerAmountFilled, uint256 takerAmountFilled, uint256 fee, bytes32 builder, bytes32 metadata)
```

**topic0:** `0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee`
(keccak256 of `OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)`)

**Raw log structure from `eth_getLogs`:**
```
topics[0] = 0xd543adfd...d8ee            (event selector, always)
topics[1] = bytes32 orderHash            (indexed)
topics[2] = address maker (left-padded)  (indexed)
topics[3] = address taker (left-padded)  (indexed)
data       = ABI-encoded tuple of 7 x 32-byte words:
  word 0: uint8  side               (0 = BUY, 1 = SELL)
  word 1: uint256 tokenId           (ERC-1155 position ID — the shares leg)
  word 2: uint256 makerAmountFilled (6-dp fixed-point USDC or shares)
  word 3: uint256 takerAmountFilled (6-dp fixed-point shares or USDC)
  word 4: uint256 fee               (6-dp fixed-point USDC)
  word 5: bytes32 builder           (builder address hash, usually 0x0)
  word 6: bytes32 metadata          (order metadata, usually 0x0)
```

**Decode recipe for raw-log → dict (for our parser):**

```python
# Given: log = eth_getLogs response object
order_hash  = log["topics"][1]                              # hex bytes32
maker_addr  = "0x" + log["topics"][2][-40:]                # strip padding
taker_addr  = "0x" + log["topics"][3][-40:]                # strip padding
data_bytes  = bytes.fromhex(log["data"][2:])               # strip 0x
words       = [int.from_bytes(data_bytes[i:i+32], "big") for i in range(0, 224, 32)]
side              = words[0]      # 0=BUY, 1=SELL
token_id          = words[1]      # ERC-1155 position ID (shares token)
maker_amount      = words[2]      # 6-dp
taker_amount      = words[3]      # 6-dp
fee               = words[4]      # 6-dp
builder           = words[5]      # bytes32 (usually 0)
metadata          = words[6]      # bytes32 (usually 0)
```

**V2 vs V1 schema difference (CRITICAL for parser):**
- V1 (`0x4bFb…982E`) event had: `side` ABSENT, `makerAssetId` (uint256), `takerAssetId` (uint256) — 8 params total
- V2 (`0xE111…996B`) event has: `side` (uint8), `tokenId` (single uint256) — 10 params total
- The existing parser (`src/pat/data/polymarket_history.py`) uses `makerAssetId`/`takerAssetId` key names — these are V1 names. The raw-log adapter must translate V2 fields.

**Adapting V2 fields to the current parser's expected dict:**

The parser uses `makerAssetId`/`takerAssetId` to determine which leg is USDC vs shares.
In V2, `tokenId` is always the **shares token**; USDC (assetId = "0") is implicit.
Translation rule:
```
if side == 0 (BUY):  maker gives USDC,  taker gives shares
    → makerAssetId = "0",      takerAssetId = str(token_id)
if side == 1 (SELL): maker gives shares, taker gives USDC
    → makerAssetId = str(token_id), takerAssetId = "0"
```
This maps V2 to the existing parser's collateral-detection logic without changing the parser.

**Timestamp:** `eth_getLogs` returns `blockNumber` (hex), NOT a timestamp.
- Obtain timestamp via `eth_getBlockByNumber(blockNumber, false)["timestamp"]` (hex → int, Unix epoch **seconds**).
- The parser expects `timestamp` in epoch milliseconds → multiply by 1000.
- Cost: Alchemy charges 20 CU per `eth_getBlockByNumber` call.
- **Optimization:** deduplicate by block number — one call per unique block, not per event.
  Polygon produces ~1 block every 2s, so a batch of 1000 events typically spans far fewer
  than 1000 unique blocks.

**I8 resolved:** maker/taker addresses ARE present as indexed topics. Copy-trading attribution
(C1) is technically feasible via `topics[2]`/`topics[3]` filtering in `eth_getLogs`. See ADR 0016.

---

### I9 — Gamma geopolitics market selection (VERIFIED, 2026-06-07)

**Sources:** live `gamma-api.polymarket.com/events?tag_id=100265`; `clob.polymarket.com/fee-rate?token_id=<id>` → `base_fee` bps; docs.polymarket.com gamma-openapi.

- **Recipe:** `GET /events?tag_id=100265&limit=500[&offset=]` (geopolitics tag id `100265`). Each
  `events[].markets[]` carries `clobTokenIds: [YES_id, NO_id]` — the ERC-1155 token_ids that appear
  in `OrderFilled`. ~35–40 events total (live + historical; `closed=true` still returns ids) → 1–2 pages.
- **🔴 geopolitics TAG ≠ 0% fee.** Some geopolitics-tagged markets ("Xi out before 2027", "Erdogan
  out 2026") have `feesEnabled=true`, `feeType="politics_fees"` (4%). The **definitive 0%-fee
  selector is `feesEnabled=false` (≡ `feeType=null`)** on the market object, NOT the tag. For the
  clean 0%-fee MM backtest, select tokens by `feesEnabled=false`; cross-check per token via
  `clob /fee-rate` (`base_fee=0`).
- **Design implication:** Gamma/CLOB expose **per-market fee data** (`feesEnabled`, `feeType`,
  `feeSchedule={exponent,rate,takerOnly,rebateRate}`) — richer than our static `Category→rate`
  table. Whether to drive the cost model from live per-market fees vs the static table is a
  **Phase-2b decision** (route through `fee-cost-auditor`). Refines **C6**: "geopolitics 0%" holds
  only for `feesEnabled=false` markets.

### I10 — NegRisk OrderFilled ABI vs main exchange (VERIFIED, 2026-06-08)

**Question:** does `0xe2222d279d744050d28e00520010520000310F59` (NegRisk CTF Exchange V2) emit the
identical `OrderFilled` event (topic0 + non-indexed data layout) as the main exchange
`0xE111180000d2663C0091e4f400237545B87B996B` so that the existing decoder works unchanged?

**Primary sources:**
- GitHub raw `src/exchange/mixins/Events.sol` (ctf-exchange-v2, branch main) — contains
  `bytes32 private constant _ORDER_FILLED_TOPIC = keccak256("OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)");`
- GitHub raw `src/exchange/interfaces/ITrading.sol` — canonical event declaration
- GitHub raw `src/exchange/CTFExchange.sol` — contract declaration:
  `contract CTFExchange is Auth, ERC1155TokenReceiver, Pausable, Trading`
- Polygonscan verified source for `0xe2222...0F59`: contract name `CTFExchange`, same source
  files (Events.sol, Trading.sol, etc.)
- Live tx `0xcc667e6a64a151718069671341b33335dab5e05cb669f26baae35270b24e3968` on the NegRisk
  contract, Polygon, checked 2026-06-08

**Structural finding:**
The NegRisk CTF Exchange V2 (`0xe2222...0F59`) is NOT a separate contract with a different
implementation. Polygonscan confirms it is **the identical `CTFExchange` Solidity contract**
(same verified source, same inheritance chain: CTFExchange → Trading → Events mixin). There
is no NegRisk-specific redefinition of `OrderFilled`.

**topic0 confirmed on-chain (NegRisk contract):**
```
0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee
```
(matches main exchange exactly — same `Events.sol` constant)

**Non-indexed data layout confirmed from live NegRisk tx (Log 916 of tx 0xcc667e6a…):**
```
data = 7 x 32-byte ABI-encoded words:
  word 0: side               = 0x01 (SELL)
  word 1: tokenId            = 0x39a8db032a38d5a3328d7ac12a5049384657152c00bad97eac94caf2ac53e29c
  word 2: makerAmountFilled  = 0x01755a74 (24,534,644 → 24.534644 USDC)
  word 3: takerAmountFilled  = 0x015ef3be (23,069,630)
  word 4: fee                = 0x00 (zero — NegRisk geo market, 0% fee)
  word 5: builder            = 0x00
  word 6: metadata           = 0x00
```
Order and types match the main exchange layout exactly.

**NegRisk-specific events (irrelevant to OrderFilled decoder):**
The `INegRiskAdapter` contract emits: `PositionsConverted`, `MarketPrepared`, `QuestionPrepared`,
`PositionSplit`, `PositionsMerge`, `OutcomeReported`, `PayoutRedemption`. These are on the
**adapter contract** (`0xAdA200001000ef00D07553cEE7006808F895c6F1`), not the exchange. They
carry no `OrderFilled` data and do not affect our decoder.

**Verdict:** The existing `OrderFilled` decoder written for the main exchange requires **zero
changes** to decode NegRisk exchange logs. The same `eth_getLogs` call targeting
`0xe2222...0F59` with topic0 `0xd543adfd...d8ee` and the same 7-word decode recipe applies.
A unified multi-address log fetch (both exchanges in one `address` array) is safe.

---

### How to update this file
On any new verification: change Status, add source URL + date + one-line finding, and write an
ADR if the design changes. Re-check `STALE`-prone items (C9, gas, geo-blocks) before live.
