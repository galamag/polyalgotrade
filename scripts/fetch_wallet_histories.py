"""Fetch top-wallet + control on-chain OrderFilled history across all 4 Polymarket exchanges.

USER-RUNS THIS (Alchemy key in POLYGON_RPC_URL). Per wallet, two topic-filtered passes
(maker=topics[2], taker=topics[3]) per exchange, merged. Saves data/raw/wallets/<addr>.json.
Also reports a topic0 histogram per wallet -> the measure-first V1 gate (spec §6, S4): if V1
OrderFilled > 20% of fills for the MEDIAN wallet, we build a V1 decoder before features.
The numerator is a conservative over-count (non-OrderFilled V1 events included) until the
true V1 OrderFilled topic0 is identified from the dumped histograms.

🔴 Never read .env — the key lives in POLYGON_RPC_URL or is passed via --rpc-url.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

# --- sys.path bootstrap so `python scripts/...` finds the src/ package ---------
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import structlog  # noqa: E402

from pat.analytics.wallet_control import sample_control_wallets  # noqa: E402
from pat.data.wallet_history import merge_maker_taker, wallet_to_topic  # noqa: E402
from pat.venues.polymarket.leaderboard import fetch_leaderboard  # noqa: E402
from scripts.fetch_polymarket_history import _rpc_get_logs  # noqa: E402

# topic0s per exchange. V2 OrderFilled is known; V1 OrderFilled topic0 is observed from the
# histogram on first run (spec §6) — keep V1 as None to fetch ALL of the wallet's V1 logs.
V2_TOPIC0 = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
EXCHANGES: list[tuple[str, str | None]] = [
    ("0xE111180000d2663C0091e4f400237545B87B996B", V2_TOPIC0),  # V2 main
    ("0xe2222d279d744050d28e00520010520000310F59", V2_TOPIC0),  # V2 neg-risk
    ("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E", None),       # V1 main (observe topic0)
    ("0xC5d563A36AE78145C45a50134d48A1215220f80a", None),       # V1 neg-risk (observe topic0)
]

log = structlog.get_logger(__name__)


def topic0_histogram(logs: list[dict[str, Any]]) -> dict[str, int]:
    """Count logs by topics[0] (lowercased) — used to identify/measure V1 vs V2 OrderFilled."""
    c: Counter[str] = Counter()
    for entry in logs:
        topics = entry.get("topics") or []
        if topics:
            c[str(topics[0]).lower()] += 1
    return dict(c)


def v1_fraction_for_wallet(hist: dict[str, int]) -> float | None:
    """Per-wallet V1-or-other fraction. Returns None if no logs (skip in median)."""
    v2 = hist.get(V2_TOPIC0.lower(), 0)
    v1 = sum(v for k, v in hist.items() if k != V2_TOPIC0.lower())
    total = v1 + v2
    return (v1 / total) if total > 0 else None


def fetch_one_wallet(
    wallet: str,
    *,
    rpc_url: str,
    from_block: int,
    to_block: int,
    exchanges_topic0: list[tuple[str, str | None]],
) -> list[dict[str, Any]]:
    """Two topic-filtered passes (maker, taker) per exchange, merged + deduped."""
    wtopic = wallet_to_topic(wallet)
    maker_logs: list[dict[str, Any]] = []
    taker_logs: list[dict[str, Any]] = []
    for address, topic0 in exchanges_topic0:
        maker_logs += _rpc_get_logs(rpc_url, address, from_block, to_block,
                                    topics=[topic0, None, wtopic])
        taker_logs += _rpc_get_logs(rpc_url, address, from_block, to_block,
                                    topics=[topic0, None, None, wtopic])
    return merge_maker_taker(maker_logs, taker_logs)


def run(
    out_dir: Path,
    *,
    from_block: int,
    to_block: int,
    top_n: int,
    control_n: int,
    control_src: Path,
    rpc_url: str | None = None,
) -> Path:
    corr_id = str(uuid.uuid4())
    blog = log.bind(corr_id=corr_id, from_block=from_block, to_block=to_block)
    effective_rpc = rpc_url or os.environ.get("POLYGON_RPC_URL")
    if not effective_rpc:
        raise SystemExit("Set POLYGON_RPC_URL (or pass --rpc-url). Never read .env.")

    out_dir.mkdir(parents=True, exist_ok=True)
    leaders = fetch_leaderboard(top_n=top_n)
    winners = [e.wallet for e in leaders]
    control_events = json.loads(control_src.read_text(encoding="utf-8"))
    control = sample_control_wallets(control_events, n=control_n, exclude=set(winners))
    (out_dir / "_winners.json").write_text(json.dumps(winners), encoding="utf-8")
    (out_dir / "_control.json").write_text(json.dumps(control), encoding="utf-8")
    blog.info("wallets.selected", winners=len(winners), control=len(control))

    # Collect per-wallet topic0 histograms and V1 fractions (S4)
    v1_fractions: list[float] = []
    all_histograms: dict[str, dict[str, int]] = {}

    for wallet in (*winners, *control):
        wallet_logs = fetch_one_wallet(
            wallet,
            rpc_url=effective_rpc,
            from_block=from_block,
            to_block=to_block,
            exchanges_topic0=EXCHANGES,
        )
        hist = topic0_histogram(wallet_logs)
        all_histograms[wallet] = hist

        # Per-wallet V1 fraction for median computation (S4)
        frac = v1_fraction_for_wallet(hist)
        if frac is not None:
            v1_fractions.append(frac)

        v2 = hist.get(V2_TOPIC0.lower(), 0)
        v1 = sum(v for k, v in hist.items() if k != V2_TOPIC0.lower())
        (out_dir / f"{wallet}.json").write_text(
            json.dumps(wallet_logs, indent=2), encoding="utf-8"
        )
        blog.info("wallet.fetched", wallet=wallet, n=len(wallet_logs), v2=v2, v1_or_other=v1)

    # Write per-wallet topic0 histograms so V1 topic0 can be identified from observations (S4)
    (out_dir / "_topic0_histograms.json").write_text(
        json.dumps(all_histograms, indent=2), encoding="utf-8"
    )

    # Median over wallets (not pooled) — conservative over-count until V1 topic0 confirmed (S4)
    v1_share = statistics.median(v1_fractions) if v1_fractions else 0.0
    blog.info(
        "v1_gate",
        v1_share=round(v1_share, 3),
        decision="BUILD_V1_DECODER" if v1_share > 0.20 else "V2_ONLY_OK",
        note="numerator is conservative over-count (non-OrderFilled V1 events included)",
    )
    return out_dir


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch top-wallet + control OrderFilled history.")
    p.add_argument("--from-block", type=int, required=True)
    p.add_argument("--to-block", type=int, required=True)
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument("--control-n", type=int, default=25)
    p.add_argument(
        "--control-src",
        type=Path,
        default=Path("data/raw/geopolitics_88082000_88090000.json"),
    )
    p.add_argument("--out-dir", type=Path, default=Path("data/raw/wallets"))
    p.add_argument("--rpc-url", type=str, default=None)
    return p.parse_args()


if __name__ == "__main__":
    import logging

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    args = _parse_args()
    result = run(
        args.out_dir,
        from_block=args.from_block,
        to_block=args.to_block,
        top_n=args.top_n,
        control_n=args.control_n,
        control_src=args.control_src,
        rpc_url=args.rpc_url,
    )
    print(result)  # noqa: T201
