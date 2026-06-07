"""Fetch Polymarket CTF Exchange V2 OrderFilled logs via Polygon JSON-RPC.

Usage (CLI):
    uv run python scripts/fetch_polymarket_history.py --from-block 60000000 --to-block 60010000

The script pages through blocks in chunks of POLYGON_MAX_BLOCK_RANGE (default 1000),
writing raw JSON to data/raw/orderfilled_{from}_{to}.json.  It is resumable: re-run
with the same block range and the file is overwritten (idempotent raw layer).

Network isolation:
    ALL network I/O lives in _rpc_get_logs().  Tests monkeypatch that function
    so the rest of the pipeline runs without touching the network.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
import structlog

# ── Constants ─────────────────────────────────────────────────────────────────

# Verified in ADR 0007.  Do not hard-code if claim C1 is ever re-opened.
EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"
GAMMA = "https://gamma-api.polymarket.com"

_DEFAULT_RPC = "https://polygon-rpc.com"
_DEFAULT_MAX_BLOCK_RANGE = 1000
_REQUEST_TIMEOUT = 30  # seconds — explicit to satisfy ruff S113

log = structlog.get_logger(__name__)


# ── Network seam (only function that touches the wire) ────────────────────────


def _rpc_get_logs(
    rpc_url: str,
    address: str,
    from_block: int,
    to_block: int,
) -> list[dict[str, Any]]:
    """Fetch eth_getLogs for *address* over [from_block, to_block] via JSON-RPC.

    Pages through the range in chunks of POLYGON_MAX_BLOCK_RANGE so we stay
    within provider limits.  Returns the concatenated raw result list.

    This is the ONLY function that touches the network.  Monkeypatch it in
    tests to avoid real HTTP calls.
    """
    max_range = int(os.environ.get("POLYGON_MAX_BLOCK_RANGE", _DEFAULT_MAX_BLOCK_RANGE))
    results: list[dict[str, Any]] = []

    chunk_start = from_block
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        while chunk_start <= to_block:
            chunk_end = min(chunk_start + max_range - 1, to_block)
            payload: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getLogs",
                "params": [
                    {
                        "address": address,
                        "fromBlock": hex(chunk_start),
                        "toBlock": hex(chunk_end),
                    }
                ],
            }
            log.debug(
                "rpc.eth_getLogs.request",
                from_block=chunk_start,
                to_block=chunk_end,
                rpc_url=rpc_url,
            )
            response = client.post(rpc_url, json=payload)
            response.raise_for_status()
            body = response.json()

            if "error" in body:
                raise RuntimeError(f"JSON-RPC error: {body['error']}")

            chunk_results: list[dict[str, Any]] = body.get("result", [])
            log.debug(
                "rpc.eth_getLogs.response",
                from_block=chunk_start,
                to_block=chunk_end,
                count=len(chunk_results),
            )
            results.extend(chunk_results)
            chunk_start = chunk_end + 1

    return results


# ── Main pipeline function ─────────────────────────────────────────────────────


def run(
    out_dir: Path,
    from_block: int,
    to_block: int,
    rpc_url: str | None = None,
) -> Path:
    """Fetch OrderFilled logs and write raw JSON to *out_dir*.

    Parameters
    ----------
    out_dir:
        Directory to write raw output.  Created if it does not exist.
    from_block:
        First block to query (inclusive).
    to_block:
        Last block to query (inclusive).
    rpc_url:
        Polygon JSON-RPC endpoint.  Defaults to env POLYGON_RPC_URL or
        the public https://polygon-rpc.com endpoint.

    Returns
    -------
    Path
        Absolute path of the written JSON file.
    """
    corr_id = str(uuid.uuid4())
    bound_log = log.bind(corr_id=corr_id, from_block=from_block, to_block=to_block)

    effective_rpc = rpc_url or os.environ.get("POLYGON_RPC_URL", _DEFAULT_RPC)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"orderfilled_{from_block}_{to_block}.json"

    bound_log.info(
        "fetch.start",
        rpc_url=effective_rpc,
        exchange=EXCHANGE_V2,
        out_path=str(out_path),
    )

    logs = _rpc_get_logs(
        rpc_url=effective_rpc,
        address=EXCHANGE_V2,
        from_block=from_block,
        to_block=to_block,
    )

    bound_log.info("fetch.complete", count=len(logs), out_path=str(out_path))

    out_path.write_text(json.dumps(logs, indent=2), encoding="utf-8")

    bound_log.info("fetch.written", out_path=str(out_path), bytes=out_path.stat().st_size)

    return out_path


# ── CLI entry-point ────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Polymarket OrderFilled logs from Polygon JSON-RPC."
    )
    parser.add_argument(
        "--from-block",
        type=int,
        required=True,
        help="First block number to query (inclusive).",
    )
    parser.add_argument(
        "--to-block",
        type=int,
        required=True,
        help="Last block number to query (inclusive).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/raw"),
        help="Output directory for raw JSON files (default: data/raw).",
    )
    parser.add_argument(
        "--rpc-url",
        type=str,
        default=None,
        help="Polygon JSON-RPC URL (overrides POLYGON_RPC_URL env var).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    import logging

    import structlog

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )

    args = _parse_args()
    result_path = run(
        out_dir=args.out_dir,
        from_block=args.from_block,
        to_block=args.to_block,
        rpc_url=args.rpc_url,
    )
    print(result_path)  # noqa: T201
