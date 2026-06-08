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

import argparse
import json
from decimal import Decimal
from pathlib import Path
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
    """Print the parameter-sweep frontier as an aligned table (one row per half_spread)."""
    print("half_spread | n_trades | net_pnl | inv_value | sharpe | advance")
    for r in rows:
        res, v = r["result"], r["verdict"]
        print(
            f"  {r['half_spread']!s:>9} | {res.n_trades:>8} | {res.net_pnl:>7} | "
            f"{res.inventory_value:>9} | {res.sharpe:>6.3f} | {v.advance}"
        )


RESULTS_START = "<!-- RESULTS:START -->"
RESULTS_END = "<!-- RESULTS:END -->"


def render_frontier_markdown(rows: list[dict[str, Any]], *, provenance: dict[str, Any]) -> str:
    """Render the sweep frontier as a markdown table + verdict + §8 caveats + provenance."""
    header = (
        "| half_spread | n_trades | net_pnl | gross_pnl | fee_drag "
        "| inv_value | win_rate | max_dd | sharpe | advance |"
    )
    lines = [header, "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        res, v = r["result"], r["verdict"]
        lines.append(
            f"| {r['half_spread']} | {res.n_trades} | {res.net_pnl} "
            f"| {res.gross_pnl} | {res.fee_drag} | {res.inventory_value} "
            f"| {res.win_rate:.3f} | {res.max_drawdown} | {res.sharpe:.3f} "
            f"| {v.advance} |"
        )
    prov = ", ".join(f"{k}={val}" for k, val in provenance.items())
    caveats = (
        "_Caveats (§8): sharpe is per-fill (relative ranking, not "
        "annualized); win_rate ~50% by construction for a two-sided MM "
        "(lean on net_pnl incl. inventory MtM); sharpe & max_dd are "
        "realized-only; fills are a conservative lower bound (through-trade "
        "proxy, no order book — real proof is paper, Phase 3)._"
    )
    return "\n".join(lines) + f"\n\n**Provenance:** {prov}\n\n{caveats}\n"


def write_results_section(doc_path: Path, section_md: str) -> None:
    """Replace the content between RESULTS markers in *doc_path* with *section_md*."""
    text = doc_path.read_text(encoding="utf-8")
    start = text.index(RESULTS_START) + len(RESULTS_START)
    end = text.index(RESULTS_END)
    doc_path.write_text(text[:start] + "\n" + section_md + "\n" + text[end:], encoding="utf-8")


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
    parser.add_argument("--record", type=Path, default=None,
                        help="If set, write the frontier into the RESULTS markers of this doc "
                             "(e.g. docs/strategies/market-making.md).")
    args = parser.parse_args()

    log.info("mm_backtest.start", json_path=args.json_path)

    with open(args.json_path, encoding="utf-8") as fh:
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

    import uuid as _uuid

    from pat.logging import TradeJournal

    corr_id = str(_uuid.uuid4())
    journal = TradeJournal(
        path=Path("logs") / "mm_backtest.jsonl", mode="backtest", corr_id=corr_id
    )
    for r in rows:
        res, v = r["result"], r["verdict"]
        journal.record(event="verdict", strategy="market_maker", reason=v.reason,
                       half_spread=str(r["half_spread"]), n_trades=res.n_trades,
                       net_pnl=str(res.net_pnl), sharpe=res.sharpe, fee=str(res.fee_drag),
                       advance=v.advance)
    if args.record is not None:
        provenance = {"json_path": args.json_path, "tokens": len(streams),
                      "max_n_trades": max((r["result"].n_trades for r in rows), default=0)}
        write_results_section(args.record, render_frontier_markdown(rows, provenance=provenance))
        log.info("mm_backtest.verdict_recorded", doc=str(args.record))

    log.info("mm_backtest.done")
