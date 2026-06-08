"""Orchestrate the Phase-2b geopolitics data fetch into a backtest-ready decoded JSON.

Pipeline (ordered for CU economy — timestamps only for geo fills):
    Gamma select 0%-fee geopolitics tokens
    -> eth_getLogs OrderFilled across [EXCHANGE_V2, NEGRISK_V2] (topic0-filtered)
    -> decode_v2_orderfilled
    -> filter to the geopolitics token set
    -> enrich_timestamps (one eth_getBlockByNumber per unique geo block)
    -> quarantine events that fail the parser
    -> write data/raw/geopolitics_{from}_{to}.json (with maker/taker preserved)

The resulting file is consumed UNCHANGED by scripts/run_mm_backtest.py.

Network isolation: all wire I/O is in the seams of the imported modules
(gamma._gamma_get_events, gamma._clob_get_fee_rate, fetch_polymarket_history._rpc_get_logs,
polymarket_on_chain._rpc_get_block_timestamp). Tests monkeypatch those.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from pat.data.polymarket_history import parse_orderfilled
from pat.data.polymarket_on_chain import decode_v2_orderfilled, enrich_timestamps
from pat.logging import TradeJournal
from pat.venues.polymarket import gamma

# Allow direct execution (`python scripts/fetch_geopolitics_data.py`): running a file by path puts
# the script's own dir on sys.path[0], not the project root, so the sibling `scripts.*` import below
# would fail. Put the project root on sys.path first. pytest (pythonpath=".") and `python -m
# scripts.fetch_geopolitics_data` already have the root on the path, so this is a no-op there.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.fetch_polymarket_history import (  # noqa: E402
    EXCHANGE_V2,
    NEGRISK_V2,
    fetch_orderfilled_logs,
)

log = structlog.get_logger(__name__)


def _validate_and_quarantine(
    events: list[dict[str, Any]], journal: TradeJournal
) -> list[dict[str, Any]]:
    """Drop events that fail the parser (price>1, size<=0, etc.), counting them."""
    clean: list[dict[str, Any]] = []
    quarantined = 0
    for ev in events:
        try:
            parse_orderfilled([ev])  # reuse the parser as the validator (DRY)
        except (ValidationError, KeyError, ValueError):
            quarantined += 1
            journal.record(event="quarantine", reason="parse_failed", tx=ev.get("transactionHash"))
            continue
        clean.append(ev)
    log.info("geopolitics.quarantine", clean=len(clean), quarantined=quarantined)
    return clean


def run(
    out_dir: Path,
    from_block: int,
    to_block: int,
    rpc_url: str | None = None,
    *,
    cross_check: bool = False,
) -> Path:
    """Produce the geopolitics-only decoded JSON for [from_block, to_block]."""
    corr_id = str(uuid.uuid4())
    effective_rpc = rpc_url or os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"geopolitics_{from_block}_{to_block}.json"
    journal = TradeJournal(
        path=out_dir / "geopolitics_fetch.jsonl", mode="backtest", corr_id=corr_id
    )
    bound = log.bind(corr_id=corr_id, from_block=from_block, to_block=to_block)

    # 1. Gamma selection
    events = gamma._gamma_get_events()
    geo_tokens = gamma.select_geopolitics_tokens(events, cross_check=cross_check)
    journal.record(event="gamma_selection", tokens=len(geo_tokens))
    bound.info("geopolitics.tokens_selected", tokens=len(geo_tokens))

    # 2. Fetch all OrderFilled across both exchanges (topic0-filtered)
    raw_logs = fetch_orderfilled_logs(
        effective_rpc, [EXCHANGE_V2, NEGRISK_V2], from_block, to_block
    )
    bound.info("geopolitics.logs_fetched", raw_logs=len(raw_logs))

    # 3. Decode (skip non-OrderFilled)
    decoded = [d for raw in raw_logs if (d := decode_v2_orderfilled(raw)) is not None]

    # 4. Filter to the geopolitics token set BEFORE timestamps (the CU saving)
    geo_events = [d for d in decoded if d["tokenId"] in geo_tokens]
    bound.info("geopolitics.filtered", decoded=len(decoded), geo=len(geo_events))

    # 5. Enrich timestamps (one RPC per unique geo block)
    geo_events = enrich_timestamps(geo_events, effective_rpc)

    # 6. Quarantine parser-failing events
    clean = _validate_and_quarantine(geo_events, journal)

    # 7. Write
    out_path.write_text(json.dumps(clean, indent=2, default=str), encoding="utf-8")
    journal.record(event="fetch_complete", raw_logs=len(raw_logs), decoded=len(decoded),
                   geo=len(geo_events), written=len(clean), out_path=str(out_path))
    bound.info("geopolitics.written", written=len(clean), out_path=str(out_path))
    return out_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch geopolitics 0%-fee OrderFilled data.")
    parser.add_argument("--from-block", type=int, required=True)
    parser.add_argument("--to-block", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--rpc-url", type=str, default=None)
    parser.add_argument("--cross-check", action="store_true",
                        help="Also verify base_fee==0 per token via the CLOB /fee-rate endpoint.")
    return parser.parse_args()


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
    result = run(out_dir=args.out_dir, from_block=args.from_block, to_block=args.to_block,
                 rpc_url=args.rpc_url, cross_check=args.cross_check)
    print(result)  # noqa: T201
