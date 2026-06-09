"""Keyless driver: fetch tagged /trades for top-N leaderboard winners + control wallets.

Network isolation: `fetch_trades` and `get_leaderboard` are injectable seams — monkeypatch in
tests. No .env read; no RPC key required. Idempotent: existing <wallet>.json files are skipped
unless --refresh.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import structlog  # noqa: E402

from pat.analytics.wallet_control import sample_control_wallets  # noqa: E402
from pat.venues.polymarket.leaderboard import LeaderEntry, fetch_leaderboard  # noqa: E402
from pat.venues.polymarket.trades import fetch_user_trades, tag_maker_taker  # noqa: E402

log = structlog.get_logger(__name__)


def run(
    out_dir: Path,
    *,
    top_n: int,
    control_n: int,
    control_src: Path,
    max_trades: int = 2000,
    refresh: bool = False,
    get_leaderboard: Any = None,
    fetch_trades: Any = None,
) -> Path:
    """Fetch tagged trades for winners + control; write per-wallet JSON files.

    Returns *out_dir* (always) so callers can chain.
    """
    corr_id = str(uuid.uuid4())
    blog = log.bind(corr_id=corr_id, top_n=top_n, control_n=control_n)

    leaders: list[LeaderEntry] = (get_leaderboard or fetch_leaderboard)(top_n=top_n)
    winners = [e.wallet for e in leaders]

    control_events: list[dict[str, Any]] = json.loads(
        control_src.read_text(encoding="utf-8")
    )
    control = sample_control_wallets(control_events, n=control_n, exclude=set(winners))

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "_winners.json").write_text(json.dumps(winners), encoding="utf-8")
    (out_dir / "_control.json").write_text(json.dumps(control), encoding="utf-8")
    blog.info("wallets.selected", winners=len(winners), control=len(control))

    tf = fetch_trades or fetch_user_trades

    for wallet in (*winners, *control):
        wallet_file = out_dir / f"{wallet}.json"
        if wallet_file.exists() and not refresh:
            blog.info("wallet.cached", wallet=wallet)
            continue

        all_t: list[dict[str, Any]] = tf(wallet, taker_only=False, max_trades=max_trades)
        taker_t: list[dict[str, Any]] = tf(wallet, taker_only=True, max_trades=max_trades)
        tagged = tag_maker_taker(all_t, taker_t)

        wallet_file.write_text(json.dumps(tagged, indent=2), encoding="utf-8")
        blog.info(
            "wallet.fetched",
            wallet=wallet,
            n=len(tagged),
            n_maker=sum(1 for t in tagged if t.get("is_maker")),
        )

    return out_dir


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch tagged /trades for leaderboard winners + control wallets (keyless)."
    )
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument("--control-n", type=int, default=25)
    p.add_argument("--max-trades", type=int, default=2000)
    p.add_argument(
        "--control-src",
        type=Path,
        default=Path("data/raw/geopolitics_88082000_88090000.json"),
    )
    p.add_argument("--out-dir", type=Path, default=Path("data/raw/wallet_trades"))
    p.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch wallets even if <wallet>.json already exists.",
    )
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
        top_n=args.top_n,
        control_n=args.control_n,
        control_src=args.control_src,
        max_trades=args.max_trades,
        refresh=args.refresh,
    )
    print(result)  # noqa: T201
