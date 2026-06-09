"""v2 inventory-skew spike — does skew move the v1 MM toward +EV on the existing geopolitics data?

Sweeps gamma (mid-shift) + skew_delta (asymmetric spread) at two half-spreads and prints per-hs
tables (gamma-trend / delta-trend / combo). 0 CU (no network). Reads the saved decoded JSON.
Spec: docs/superpowers/specs/2026-06-09-v2-mm-skew-spike-design.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pat.core.types import Category, Market, Venue  # noqa: E402
from pat.data.polymarket_history import parse_orderfilled  # noqa: E402
from pat.logging import TradeJournal  # noqa: E402
from scripts.run_mm_backtest import (  # noqa: E402
    run_skew_sweep,
    run_sweep,
    streams_from_fills,
)

log = structlog.get_logger(__name__)

HALF_SPREADS = [Decimal("0.01"), Decimal("0.03")]
GAMMAS = [Decimal("0"), Decimal("0.02"), Decimal("0.04"), Decimal("0.06"), Decimal("0.10")]
DELTAS = [Decimal("0.02"), Decimal("0.04"), Decimal("0.06"), Decimal("0.10")]
COMBO = [(Decimal("0.02"), Decimal("0.02")), (Decimal("0.04"), Decimal("0.04")),
         (Decimal("0.06"), Decimal("0.06"))]
_SIZE, _CAP, _ALPHA = Decimal("10"), Decimal("100"), Decimal("0.3")  # match v1 defaults


def _print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print(title)  # noqa: T201
    print("  gamma | delta |     n |   net_pnl | gross_pnl | inv_value | net/fill | resid_sh | sharpe")  # noqa: T201,E501
    for r in rows:
        res = r["result"]
        print(  # noqa: T201
            f"  {r['gamma']!s:>5} | {r['skew_delta']!s:>5} | {res.n_trades:>5} | "
            f"{res.net_pnl:>9.2f} | {res.gross_pnl:>9.2f} | {res.inventory_value:>9.2f} | "
            f"{r['net_pnl_per_fill']:>8.4f} | {r['residual_abs_shares']:>8.1f} | {res.sharpe:>6.3f}"
        )


def _configs(hs: Decimal) -> dict[str, list[dict[str, Decimal]]]:
    return {
        "gamma-trend": [{"half_spread": hs, "gamma": g, "skew_delta": Decimal("0")} for g in GAMMAS],  # noqa: E501
        "delta-trend": [{"half_spread": hs, "gamma": Decimal("0"), "skew_delta": d} for d in DELTAS],  # noqa: E501
        "combo": [{"half_spread": hs, "gamma": g, "skew_delta": d} for g, d in COMBO],
    }


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
    parser = argparse.ArgumentParser(description="v2 inventory-skew spike (0 CU, local).")
    parser.add_argument("json_path", nargs="?",
                        default="data/raw/geopolitics_88082000_88090000.json")
    args = parser.parse_args()

    raw = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    fills = parse_orderfilled(raw)
    streams = streams_from_fills(fills)
    market = Market(id="geo-skew-spike", venue=Venue.POLYMARKET,
                    question="geo-skew-spike", category=Category.GEOPOLITICS)
    log.info("skew_spike.loaded", fills=len(fills), tokens=len(streams))

    # v1 baseline n-per-hs (gamma=delta=0) -> confirm the max-n half-spread.
    base = run_sweep(streams, market=market,
                     half_spreads=[Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.05")],  # noqa: E501
                     size=_SIZE, inventory_cap=_CAP, alpha=_ALPHA)
    print("\n=== v1 baseline n-per-hs (gamma=delta=0) ===")  # noqa: T201
    for r in base:
        print(f"  hs={r['half_spread']} n={r['result'].n_trades} net={r['result'].net_pnl:.2f}")  # noqa: T201,E501

    journal = TradeJournal(path=Path("logs") / "skew_spike.jsonl", mode="backtest",
                           corr_id="skew-spike")
    for hs in HALF_SPREADS:
        for label, cfgs in _configs(hs).items():
            rows = run_skew_sweep(streams, market=market, configs=cfgs,
                                  size=_SIZE, inventory_cap=_CAP, alpha=_ALPHA)
            _print_table(f"\n=== hs={hs} | {label} ===", rows)
            for r in rows:
                journal.record(event="verdict", strategy="mm_v2_skew", half_spread=str(hs),
                               gamma=str(r["gamma"]), skew_delta=str(r["skew_delta"]),
                               n_trades=r["result"].n_trades, net_pnl=str(r["result"].net_pnl),
                               sharpe=r["result"].sharpe)
    print()  # noqa: T201
