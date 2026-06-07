# Phase 0 — Claims Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify every architecture-critical claim from the source research against a
*primary source*, so Phase 1 code is never built on a false fact. The gate: all **Critical**
claims (C1–C9) marked `VERIFIED` or `REFUTED` (not `PENDING`), each with a source URL + date.

**Architecture:** This is a *research/verification* task, not code. Each task dispatches the
`claims-verifier` subagent (model `claude-sonnet-4-6`, `effort: xhigh`) against a specific set
of primary sources, then records the result in `docs/research/claims-verification.md`. Where a
finding changes a design decision, we write an ADR. Tasks 1–6 are **independent** (different
sources) and may be parallelized; Task 7 is the synthesis barrier.

**Tech Stack:** `claims-verifier` subagent, `deep-research` skill, `WebFetch`/`WebSearch`,
Polygonscan, PyPI, GitHub. No production code in this phase.

---

## Ground rules (read before any task)

1. **Primary sources only.** Official docs (`docs.polymarket.com`, `docs.kalshi.com`), the
   actual GitHub repos, on-chain data (`polygonscan.com`), PyPI, or direct API responses.
   **Not** blogs, X/Twitter, Medium, or VPS vendors. The research itself flags its bot-P&L and
   latency numbers as second-hand — treat them as low-trust.
2. **Honesty over confirmation.** "Could not confirm" / `REFUTED` is a valid, important result.
   Never upgrade a guess to `VERIFIED`. The research is dated 2026-06-07 and contains very
   specific forward-dated claims (V2 launch, SDK names, addresses) that may be inaccurate —
   the entire point of Phase 0 is to find out *before* writing code.
3. **Recording format.** In `docs/research/claims-verification.md`, for each claim set:
   - change `Status` to `VERIFIED` / `REFUTED` / `STALE` / `PARTIAL`,
   - append to the row's notes: the **source URL** and **date checked (2026-06-07)** and a
     one-line finding.
4. **Design-affecting findings → ADR.** If a critical claim is `REFUTED` (e.g. the SDK or an
   address is wrong), write an ADR in `docs/decisions/` and STOP to discuss before Phase 1.
5. **Commit after each task** with a short message (per `CLAUDE.md` §3.2 — no co-author trailer).

### Standard step shape for every verification task
- [ ] **Dispatch:** spawn the `claims-verifier` subagent with the claim IDs, the exact claim
  text (copy from the tracker), and the candidate primary sources listed in the task.
- [ ] **Review:** read the subagent's findings; reject any conclusion not backed by a primary
  source URL; if uncertain or contradictory, dispatch `deep-research` for that single claim.
- [ ] **Record:** update the relevant rows in `docs/research/claims-verification.md` (status +
  source URL + date + one-line finding).
- [ ] **ADR (conditional):** if a finding changes the design, write `docs/decisions/000N-...md`.
- [ ] **Commit:** `git add -A && git commit -m "phase0: verify <claim-ids> (<verdict summary>)"`.

---

## Task 1 — Polymarket CTF Exchange V2 contracts & order struct (C1, C2, C3)

**Files:**
- Modify: `docs/research/claims-verification.md` (rows C1, C2, C3)
- Conditional create: `docs/decisions/0007-polymarket-v2-contract-facts.md` (only if a fact is refuted/changes design)

**Claims to verify:**
- **C1** — V2 live since 2026-04-28; exchange `0xE111180000d2663C0091e4f400237545B87B996B`,
  Neg-Risk `0xe2222d279d744050d28e00520010520000310F59`; old exchange
  `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` disabled.
- **C2** — collateral is pUSD (ERC-20, 1:1 USDC) on Polygon.
- **C3** — order struct dropped `nonce/feeRateBps/taker`, added `timestamp/metadata/builder`;
  EIP-712 Exchange domain version `"2"`.

**Primary sources to check:**
- `https://docs.polymarket.com` (CLOB / contracts / addresses sections)
- `https://github.com/Polymarket/ctf-exchange-v2` (README, `deployments/`, Solidity `Order` struct)
- `https://polygonscan.com/address/0xE111180000d2663C0091e4f400237545B87B996B` (is it a
  deployed, verified contract? recent activity?) and the old/neg-risk addresses
- Search the Polymarket org on GitHub for the exact repo name (it may differ).

- [ ] Dispatch `claims-verifier` for C1–C3 with the sources above.
- [ ] Review: require an on-chain or docs confirmation for each address; a GitHub source for
  the order struct/EIP-712 version. Flag any address that Polygonscan shows as non-existent
  or inactive.
- [ ] Record C1, C2, C3 statuses with source URLs + finding.
- [ ] If any address/struct fact is wrong → write ADR 0007 and flag for discussion.
- [ ] Commit: `phase0: verify C1-C3 polymarket v2 contracts (<verdict>)`.

---

## Task 2 — Polymarket V2 SDK (C4)

**Files:**
- Modify: `docs/research/claims-verification.md` (row C4)
- Conditional modify: `pyproject.toml` (only once VERIFIED — uncomment/pin the real package name+version)
- Conditional create: `docs/decisions/0008-polymarket-sdk-choice.md` (if the SDK name/status differs from the research)

**Claim:** **C4** — the required SDK is `py-clob-client-v2` (v1.0.1+); the old `py-clob-client`
no longer works on production; a unified `py-sdk` may also exist.

**Primary sources:**
- `https://pypi.org/project/py-clob-client-v2/` (exists? latest version? release date?)
- `https://github.com/Polymarket/py-clob-client-v2` (repo exists? active? V2 support?)
- `https://github.com/Polymarket` org listing (find the real maintained Python client + any `py-sdk`)
- `https://pypi.org/project/py-clob-client/` (is the old one deprecated/marked V1-only?)

- [ ] Dispatch `claims-verifier` for C4 with the sources above.
- [ ] Review: confirm the exact installable package name + latest version from PyPI; confirm
  V2 support from the repo README. If `py-clob-client-v2` does NOT exist, find what actually
  provides V2 access and report it.
- [ ] Record C4 status + the real package name/version + source URLs.
- [ ] If VERIFIED: update `pyproject.toml` dependency comment with the exact name+version
  (still commented until Phase 1 installs it). If the name differs: write ADR 0008.
- [ ] Commit: `phase0: verify C4 polymarket sdk (<verdict>)`.

---

## Task 3 — Polymarket fees (C5, C6, C7)

**Files:**
- Modify: `docs/research/claims-verification.md` (rows C5, C6, C7)
- Modify: `docs/architecture/fee-cost-model.md` (replace "PENDING" notes with verified
  formulas/parameters, or mark refuted)

**Claims:**
- **C5** — dynamic taker fee `C·0.07·p·(1−p)` on crypto; peak ~1.56–1.80% at p=0.50.
- **C6** — geopolitics taker fee = 0% (permanent).
- **C7** — maker rebates 25% of taker pool (20% crypto), daily in pUSD, min $1.

**Primary sources:**
- `https://docs.polymarket.com` (fees page) and the maker-rewards / liquidity-rewards docs
- Polymarket help/blog **only** if it is the official domain (`polymarket.com`)
- If reachable, a live `GET` to the CLOB market-info endpoint for a sample market's fee

- [ ] Dispatch `claims-verifier` for C5–C7.
- [ ] Review: the fee formula and the geopolitics-0% claim each need an official-docs source.
  Treat the exact rebate % as `PARTIAL` if docs give a range/different number.
- [ ] Record C5, C6, C7; then update `fee-cost-model.md` with the verified formula/params
  (these become the tested cost-model constants in Phase 1).
- [ ] Commit: `phase0: verify C5-C7 polymarket fees (<verdict>)`.

---

## Task 4 — Kalshi fees & sandbox (C8, I4)

**Files:**
- Modify: `docs/research/claims-verification.md` (rows C8, I4)

**Claims:**
- **C8** — Kalshi taker fee `round(0.07·price·(1−price), 2)` per contract; maker $0 by rounding.
- **I4** — `demo-api.kalshi.com` is a full fake-money sandbox.

**Primary sources:**
- `https://docs.kalshi.com` (fee schedule + trading API)
- Kalshi's official fee schedule page
- Kalshi API docs for the demo/sandbox base URL + how to get demo credentials

- [ ] Dispatch `claims-verifier` for C8, I4.
- [ ] Review: confirm the multiplier (0.07) and rounding behavior from the official schedule;
  confirm the demo host + that it uses fake money.
- [ ] Record C8, I4 with sources.
- [ ] Commit: `phase0: verify C8/I4 kalshi fees + sandbox (<verdict>)`.

---

## Task 5 — Kazakhstan venue access (C9)

**Files:**
- Modify: `docs/research/claims-verification.md` (row C9)
- Conditional create: `docs/decisions/0009-kz-venue-access.md` (if KZ is blocked → major replan)

**Claim:** **C9** — Kazakhstan is NOT on Polymarket's geo-block list (33 countries) nor Kalshi's
(~52 restricted), **as of today**. (This is `STALE`-prone — re-verify periodically.)

**Primary sources:**
- Polymarket Terms of Service / restricted-jurisdictions page on `polymarket.com`
- Kalshi's restricted-regions / eligibility page on `kalshi.com`

- [ ] Dispatch `claims-verifier` for C9 (check both venues' current official lists for KZ).
- [ ] Review: require the actual ToS/eligibility page; note the list's publish date.
- [ ] Record C9; mark `STALE`-recheck cadence (e.g. monthly) in the notes.
- [ ] If KZ IS blocked on either venue → write ADR 0009 and STOP for a strategy discussion
  (this would reshape the whole project).
- [ ] Commit: `phase0: verify C9 KZ venue access (<verdict>)`.

---

## Task 6 — Endpoints, rate limits, data pipeline, resolution, gas (I1, I2, I3, I5, I7)

**Files:**
- Modify: `docs/research/claims-verification.md` (rows I1, I2, I3, I5, I7)
- Modify: `docs/architecture/data-schema.md` (confirm/adjust the historical-source section if I3 differs)

**Claims:** I1 (CLOB endpoints), I2 (rate limits), I3 (`warproxxx/poly_data` reads OrderFilled
from the V2 contract via RPC + Gamma), I5 (Chainlink Data Streams auto-settle crypto markets),
I7 (Polygon gas ≈ $0.0024).

**Primary sources:**
- `https://docs.polymarket.com` (endpoints, rate limits, resolution/Chainlink)
- `https://github.com/warproxxx/poly_data` (does it exist? does it target the V2 contract?)
- `https://polygonscan.com/gastracker` (current gas) 

- [ ] Dispatch `claims-verifier` for I1, I2, I3, I5, I7.
- [ ] Review: endpoints + rate limits from docs; the data repo from GitHub; gas from
  Polygonscan. If `warproxxx/poly_data` doesn't target V2, note the gap (affects Phase-1 data plan).
- [ ] Record I1, I2, I3, I5, I7; adjust `data-schema.md` if the pipeline basis changed.
- [ ] Commit: `phase0: verify I1-I7 endpoints/data/gas (<verdict>)`.

---

## Task 7 — Synthesis, gate check & Phase-0 verdict

**Files:**
- Modify: `docs/research/claims-verification.md` (ensure no Critical row is still `PENDING`)
- Modify: `docs/roadmap.md` (tick Phase 0 boxes; record the gate result)
- Create: `docs/research/phase0-verdict.md` (summary)

- [ ] Confirm every Critical claim (C1–C9) is `VERIFIED` / `REFUTED` / `PARTIAL` — none `PENDING`.
- [ ] Write `docs/research/phase0-verdict.md`: a table of each critical claim → verdict →
  source, then a plain-English **"what this means for Phase 1"** section (e.g. confirmed SDK +
  addresses + fee constants, or — if refuted — what we must change or re-research).
- [ ] Update `docs/roadmap.md`: check the Phase 0 boxes; if the gate is met, mark Phase 1 ready;
  if critical claims are refuted, mark Phase 0 **blocked pending discussion**.
- [ ] Note L1 (VPS→CLOB latency) as **deferred** to VPS setup (needs a provisioned VPS; out of
  desk-research scope).
- [ ] Commit: `phase0: synthesis + gate check (Phase 0 complete | blocked)`.
- [ ] **STOP and report to the user** — present the verdict and the go/no-go for Phase 1.

---

## Self-Review (done at write time)

- **Spec coverage:** every Critical claim C1–C9 has a task (T1: C1-3, T2: C4, T3: C5-7,
  T4: C8, T5: C9; Important I1-7 in T4/T6). Gate (no `PENDING` Critical) enforced in T7. ✔
- **Placeholder scan:** verification *results* are intentionally produced at execution time;
  every task names exact claim IDs, exact primary-source URLs, exact files, and the recording
  format — no method placeholders. ✔
- **Consistency:** claim IDs (C1–C9, I1–I7, L1) match `docs/research/claims-verification.md`;
  ADR numbering continues from 0006 → 0007+. ✔
- **Scope:** desk verification only; latency (L1) and any code are explicitly out of scope. ✔
