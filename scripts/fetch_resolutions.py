"""Keyless: collect unique conditionIds from saved wallet trades -> Gamma resolutions.

Writes data/raw/resolutions.json: {conditionId: {"status": ..., "winning_index": ...}}.
Idempotent: RESOLVED/AMBIGUOUS records are final and never re-fetched; unresolved/unknown
are re-fetched only with --refresh. Network goes through the injectable
`fetch_markets_by_condition_ids` seam — monkeypatch in tests. No keys, no CU.
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

from pat.analytics.resolution_pnl import (  # noqa: E402
    AMBIGUOUS,
    RESOLVED,
    UNKNOWN,
    parse_resolution,
)
from pat.venues.polymarket.gamma import fetch_markets_by_condition_ids  # noqa: E402

log = structlog.get_logger(__name__)

_FINAL_STATUSES = {RESOLVED, AMBIGUOUS}


def run(
    trades_dir: Path,
    out_path: Path,
    *,
    refresh: bool = False,
    fetch_markets: Any = None,
) -> Path:
    """Fetch resolution records for every conditionId in *trades_dir*; merge + save."""
    corr_id = str(uuid.uuid4())
    blog = log.bind(corr_id=corr_id, mode="backtest")

    conds: set[str] = set()
    for f in sorted(trades_dir.glob("0x*.json")):
        for t in json.loads(f.read_text(encoding="utf-8")):
            c = t.get("conditionId")
            if c:
                conds.add(str(c))

    existing: dict[str, dict[str, Any]] = {}
    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))

    if refresh:
        todo = sorted(
            c for c in conds
            if c not in existing or existing[c]["status"] not in _FINAL_STATUSES
        )
    else:
        todo = sorted(c for c in conds if c not in existing)
    blog.info("resolutions.todo", total=len(conds), todo=len(todo), refresh=refresh)

    fm = fetch_markets or fetch_markets_by_condition_ids
    markets: list[dict[str, Any]] = fm(todo) if todo else []

    fetched: dict[str, dict[str, Any]] = {}
    for m in markets:
        rec = parse_resolution(m)
        cid = str(rec.pop("conditionId"))
        if cid:
            fetched[cid] = rec
    for c in todo:
        if c not in fetched and c not in existing:
            fetched[c] = {"status": UNKNOWN, "winning_index": None}

    merged = {**existing, **fetched}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, indent=1, sort_keys=True), encoding="utf-8")

    counts: dict[str, int] = {}
    for rec in merged.values():
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    blog.info("resolutions.saved", out=str(out_path), **counts)
    return out_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch Gamma resolutions for all saved wallet-trade conditionIds."
    )
    p.add_argument("--trades-dir", type=Path, default=Path("data/raw/wallet_trades"))
    p.add_argument("--out", type=Path, default=Path("data/raw/resolutions.json"))
    p.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch unresolved/unknown entries (resolved entries are final).",
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
    print(run(args.trades_dir, args.out, refresh=args.refresh))  # noqa: T201
