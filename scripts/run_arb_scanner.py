"""A2 structural arb scanner — long-running read-only loop (ADR 0021 Step 2).

Every --interval seconds: refresh universe (every --refresh-every scans), fetch CLOB
books, run the FROZEN spec §4 scan, append one JSONL snapshot line per scan to
data/raw/arb_scans/YYYY-MM-DD.jsonl. Keyless, $0, no orders. Ctrl+C to stop.
Coverage gaps (PC off) stay visible as timestamp gaps — that honesty is by design.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import structlog  # noqa: E402

from pat.analytics.arb_scan import (  # noqa: E402
    Universe,
    build_universe,
    scan_binary_market,
    scan_negrisk_event,
    universe_tokens,
)
from pat.venues.polymarket.books import fetch_books  # noqa: E402
from pat.venues.polymarket.gamma import fetch_active_events  # noqa: E402

log = structlog.get_logger(__name__)


def scan_once(
    universe: Universe, *, get_books: Any, max_books: int
) -> dict[str, Any]:
    """One scan: fetch books for the universe, evaluate every target, build a snapshot.

    max_books is recorded in the snapshot for traceability only; the cap itself is
    enforced by build_universe in main_loop.
    """
    started = time.time()
    tokens = universe_tokens(universe)
    books = get_books(tokens, batch_size=100)
    violations = []
    for target in universe.negrisk:
        violations.extend(scan_negrisk_event(target, books))
    for binary in universe.binaries:
        violations.extend(scan_binary_market(binary, books))
    return {
        "ts": started,
        "scan_duration_s": round(time.time() - started, 3),
        "n_events": len(universe.negrisk) + len(universe.binaries),
        "n_markets": sum(len(t.markets) for t in universe.negrisk)
        + len(universe.binaries),
        "n_books": len(books),
        "n_bad_books": len(tokens) - len(books),
        "universe_truncated": universe.truncated,
        "max_books": max_books,
        "violations": [v.model_dump(mode="json") for v in violations],
    }


def _append_snapshot(out_dir: Path, snapshot: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.fromtimestamp(snapshot["ts"], tz=UTC).strftime("%Y-%m-%d")
    path = out_dir / f"{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot) + "\n")
    return path


def main_loop(
    *,
    interval: int,
    max_books: int,
    out_dir: Path,
    max_scans: int | None = None,
    refresh_every: int = 10,
    get_events: Any = None,
    get_books: Any = None,
    sleep: Any = None,
) -> None:
    """Scan forever (or max_scans times). KeyboardInterrupt exits cleanly."""
    corr_id = str(uuid.uuid4())
    blog = log.bind(corr_id=corr_id, mode="scan")
    ge = get_events or fetch_active_events
    gb = get_books or fetch_books
    zzz = sleep or time.sleep

    universe: Universe | None = None
    n_scans = 0
    try:
        while max_scans is None or n_scans < max_scans:
            if universe is None or n_scans % refresh_every == 0:
                try:
                    events = ge()
                    universe = build_universe(events, max_books=max_books)
                    blog.info(
                        "scanner.universe", negrisk=len(universe.negrisk),
                        binaries=len(universe.binaries),
                        n_tokens=universe.n_tokens, truncated=universe.truncated,
                    )
                except Exception as exc:  # noqa: BLE001 — keep scanning on old universe
                    if universe is None:
                        raise
                    blog.warning("scanner.universe_refresh_failed", error=str(exc))
            try:
                snapshot = scan_once(universe, get_books=gb, max_books=max_books)
            except Exception as exc:  # noqa: BLE001 — one bad scan must not kill the loop
                blog.warning("scanner.scan_failed", n=n_scans, error=str(exc))
            else:
                try:
                    path = _append_snapshot(out_dir, snapshot)
                    blog.info(
                        "scanner.scan", n=n_scans,
                        violations=len(snapshot["violations"]),
                        n_books=snapshot["n_books"], out=str(path),
                    )
                except Exception as exc:  # noqa: BLE001 — write failure must not kill the loop
                    blog.warning("scanner.write_failed", n=n_scans, error=str(exc))
            n_scans += 1
            if max_scans is None or n_scans < max_scans:
                zzz(interval)
    except KeyboardInterrupt:
        blog.info("scanner.stopped", scans=n_scans)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="A2 structural arb scanner (read-only polling loop)."
    )
    p.add_argument("--interval", type=int, default=120)
    p.add_argument("--max-books", type=int, default=1500)
    p.add_argument("--out-dir", type=Path, default=Path("data/raw/arb_scans"))
    p.add_argument("--refresh-every", type=int, default=10)
    p.add_argument("--max-scans", type=int, default=None,
                   help="Stop after N scans (default: run until Ctrl+C).")
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
    main_loop(
        interval=args.interval, max_books=args.max_books, out_dir=args.out_dir,
        max_scans=args.max_scans, refresh_every=args.refresh_every,
    )
