"""Phase-2 MM backtest — parameter sweep over half_spread, net-of-fee with inventory MtM.

Pure-function core (run_sweep) is deterministic and unit-tested offline.  The
__main__ block runs it on a saved per-token trade stream (Task 8 Step 2).
Backtest fidelity is a conservative lower bound (no order book); the real verdict
is paper (ADR 0014).

Usage (requires a prior fetch via scripts/fetch_polymarket_history.py):
    uv run python scripts/run_mm_backtest.py data/raw/orderfilled_<from>_<to>.json

Optional token-id filtering (e.g. a geopolitics set) is a deferred Task-8
follow-up: the Gamma query to select geopolitics token_ids is not yet
primary-verified (CLAUDE.md principle 2).  Without a filter all tokens are used.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import structlog

from pat.analytics.metrics import Result, Verdict, summarize
from pat.core.types import Category, Fill, Market, Venue
from pat.data.polymarket_history import parse_orderfilled
from pat.execution.backtest import BacktestBroker
from pat.execution.replay import run_replay
from pat.strategies.market_maker import MarketMaker

log = structlog.get_logger(__name__)

Stream = list[tuple[Decimal, Decimal]]


def run_sweep(
    streams: dict[str, Stream],
    market: Market,
    half_spreads: list[Decimal],
    size: Decimal,
    inventory_cap: Decimal,
    alpha: Decimal,
) -> list[dict[str, Any]]:
    """Run the MM over every token stream for each half_spread; return frontier rows.

    Each row: {"half_spread", "result": Result, "verdict": Verdict}.
    Residual inventory is marked at last trade price minus a half_spread haircut.
    """
    rows: list[dict[str, Any]] = []
    for hs in half_spreads:
        fill_dicts: list[dict[str, Any]] = []
        marks: dict[str, Decimal] = {}
        for token_id, trades in streams.items():
            broker = BacktestBroker(market=market)
            mm = MarketMaker(token_id=token_id, half_spread=hs, size=size,
                             inventory_cap=inventory_cap, alpha=alpha, tick=market.tick_size)
            fills = run_replay(mm, broker, trades)
            for f in fills:
                side = mm.side_of(f.order_id)
                if side is None:
                    continue
                fill_dicts.append({"side": side.value, "price": f.price,
                                   "size": f.size, "fee": f.fee, "token_id": f.token_id})
            if trades:
                marks[token_id] = trades[-1][0]  # last trade price = mark
        result: Result = summarize(fill_dicts, marks=marks, inventory_haircut=hs)
        verdict: Verdict = Verdict.from_metrics(result.sharpe, result.net_pnl, result.n_trades)
        rows.append({"half_spread": hs, "result": result, "verdict": verdict})
    return rows


def print_frontier(rows: list[dict[str, Any]]) -> None:
    print("half_spread | n_trades | net_pnl | inv_value | sharpe | advance")  # noqa: T201
    for r in rows:
        res, v = r["result"], r["verdict"]
        print(  # noqa: T201
            f"  {r['half_spread']!s:>9} | {res.n_trades:>8} | {res.net_pnl:>7} | "
            f"{res.inventory_value:>9} | {res.sharpe:>6.3f} | {v.advance}"
        )


def streams_from_fills(fills: list[Fill], token_ids: set[str] | None = None) -> dict[str, Stream]:
    """Group parsed Fill records into per-token (price, size) streams, ts-ordered.

    Args:
        fills: list[pat.core.types.Fill] from parse_orderfilled().
        token_ids: if given, keep only these tokens (e.g. a verified geopolitics set).
            Token-category filtering (Gamma geopolitics query) is a deferred Task-8
            follow-up; the Gamma query is not yet primary-verified (CLAUDE.md §2).
            When None, all tokens are included.
    """
    by_token: dict[str, Stream] = {}
    for f in sorted(fills, key=lambda x: x.ts):
        if token_ids is not None and f.token_id not in token_ids:
            continue
        by_token.setdefault(f.token_id, []).append((f.price, f.size))
    return by_token


if __name__ == "__main__":
    # ---------------------------------------------------------------------------
    # CLI: load raw OrderFilled JSON, build streams, sweep, print frontier.
    # Token-id filtering is OPTIONAL (pass --tokens as comma-separated ids).
    # The Gamma geopolitics query to derive a token set is deferred (unverified).
    # ---------------------------------------------------------------------------
    import argparse

    parser = argparse.ArgumentParser(
        description="Run MM parameter sweep on saved OrderFilled JSON."
    )
    parser.add_argument("json_path", help="Path to raw OrderFilled JSON file.")
    parser.add_argument(
        "--tokens",
        default=None,
        help=(
            "Comma-separated token_ids to include. "
            "If omitted, all tokens are used. "
            "Geopolitics category filtering via Gamma is deferred (unverified, CLAUDE.md §2)."
        ),
    )
    parser.add_argument(
        "--half-spreads",
        default="0.01,0.02,0.03,0.05",
        help="Comma-separated half-spread values (default: 0.01,0.02,0.03,0.05).",
    )
    parser.add_argument("--size", default="10", help="Quote size per side (default: 10).")
    parser.add_argument(
        "--inventory-cap", default="100", help="Max absolute inventory per token (default: 100)."
    )
    parser.add_argument("--alpha", default="0.3", help="EWMA alpha for fair value (default: 0.3).")
    args = parser.parse_args()

    log.info("mm_backtest.start", json_path=args.json_path)

    with open(args.json_path) as fh:
        raw_events: list[dict[str, Any]] = json.load(fh)

    log.info("mm_backtest.events_loaded", count=len(raw_events))

    parsed_fills = parse_orderfilled(raw_events)
    log.info("mm_backtest.fills_parsed", count=len(parsed_fills))

    token_ids_filter: set[str] | None = None
    if args.tokens:
        token_ids_filter = set(args.tokens.split(","))
        log.info("mm_backtest.token_filter_applied", token_count=len(token_ids_filter))
    else:
        # No filter: all tokens included.
        # Geopolitics category filtering (Gamma query) is a deferred Task-8 follow-up;
        # the exact query is not yet primary-verified (claims-verification.md).
        log.info(
            "mm_backtest.no_token_filter",
            note="all tokens included; geopolitics Gamma filter is deferred (unverified)",
        )

    streams = streams_from_fills(parsed_fills, token_ids=token_ids_filter)
    log.info("mm_backtest.streams_built", token_count=len(streams))

    half_spreads = [Decimal(s) for s in args.half_spreads.split(",")]
    # Build a synthetic market object for the sweep (venue/category for cost routing).
    market = Market(
        id="polymarket-geopolitics-sweep",
        venue=Venue.POLYMARKET,
        question="geopolitics-sweep",
        category=Category.GEOPOLITICS,
    )

    rows = run_sweep(
        streams,
        market=market,
        half_spreads=half_spreads,
        size=Decimal(args.size),
        inventory_cap=Decimal(args.inventory_cap),
        alpha=Decimal(args.alpha),
    )
    print_frontier(rows)
    log.info("mm_backtest.done")
