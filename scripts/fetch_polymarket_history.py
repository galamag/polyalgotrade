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

from pat.data.polymarket_on_chain import TOPIC0_ORDERFILLED

# ── Constants ─────────────────────────────────────────────────────────────────

# Verified in ADR 0007.  Do not hard-code if claim C1 is ever re-opened.
EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"
GAMMA = "https://gamma-api.polymarket.com"
# NegRisk CTF Exchange V2 — geopolitics multi-outcome markets often trade here.
# VERIFIED (claim I10, 2026-06-08): `NegRiskCtfExchange is CTFExchange{}` emits the IDENTICAL V2
# OrderFilled (topic0 0xd543adfd...d8ee, 7-word layout) as the main exchange — decoder unchanged.
# (It also emits OrdersMatched topic0 0x174b3811...; excluded by our topic0 filter.)
NEGRISK_V2 = "0xe2222d279d744050d28e00520010520000310F59"

_DEFAULT_RPC = "https://polygon-rpc.com"
_DEFAULT_MAX_BLOCK_RANGE = 1000
_REQUEST_TIMEOUT = 30  # seconds — explicit to satisfy ruff S113

log = structlog.get_logger(__name__)


# ── Network seam (only function that touches the wire) ────────────────────────


def _build_getlogs_payload(
    address: str, from_block: int, to_block: int, topics: list[str] | None = None
) -> dict[str, Any]:
    """Build the eth_getLogs JSON-RPC payload. Pure (no I/O) so it is unit-testable."""
    log_filter: dict[str, Any] = {
        "address": address,
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
    }
    if topics is not None:
        log_filter["topics"] = topics
    return {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [log_filter]}


def _rpc_get_logs(
    rpc_url: str,
    address: str,
    from_block: int,
    to_block: int,
    topics: list[str] | None = None,
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
            results.extend(
                _get_logs_range(client, rpc_url, address, chunk_start, chunk_end, topics)
            )
            chunk_start = chunk_end + 1

    return results


# Substrings in a provider's error message that mean "your range/result set is too big" — the
# recoverable case we handle by bisecting the block range and retrying each half.
_SIZE_LIMIT_MARKERS = (
    "response size",
    "log response",
    "more than 10000",
    "10000 results",
    "block range",
    "query returned more than",
    "query timeout",
)


def _get_logs_range(
    client: httpx.Client,
    rpc_url: str,
    address: str,
    lo: int,
    hi: int,
    topics: list[str] | None,
) -> list[dict[str, Any]]:
    """Fetch one [lo, hi] block range, auto-splitting on the getLogs size/range limit.

    Alchemy (and most providers) cap eth_getLogs by response size / block range and
    report it as an HTTP 4xx whose JSON body carries the real reason.  We parse that
    body (so the cause is visible) and, when it is a size/range limit and the range is
    splittable, bisect and recurse.  Errors are raised WITHOUT the RPC URL so the
    embedded API key never reaches logs or tracebacks.
    """
    payload = _build_getlogs_payload(address, lo, hi, topics)
    response = client.post(rpc_url, json=payload)
    try:
        body: Any = response.json()
    except ValueError:
        body = None

    err = body.get("error") if isinstance(body, dict) else None
    if err is None and response.status_code < 400:
        chunk_results: list[dict[str, Any]] = (
            body.get("result", []) if isinstance(body, dict) else []
        )
        log.debug("rpc.eth_getLogs.response", from_block=lo, to_block=hi, count=len(chunk_results))
        return chunk_results

    detail = err if err is not None else (response.text[:300] if response.text else "")
    is_size_limit = any(m in str(detail).lower() for m in _SIZE_LIMIT_MARKERS)
    if is_size_limit and lo < hi:
        mid = (lo + hi) // 2
        log.debug("rpc.eth_getLogs.split", from_block=lo, to_block=hi, mid=mid)
        return _get_logs_range(client, rpc_url, address, lo, mid, topics) + _get_logs_range(
            client, rpc_url, address, mid + 1, hi, topics
        )

    raise RuntimeError(
        f"eth_getLogs failed (HTTP {response.status_code}) for blocks [{lo}, {hi}]: {detail}"
    )


def fetch_orderfilled_logs(
    rpc_url: str,
    addresses: list[str],
    from_block: int,
    to_block: int,
) -> list[dict[str, Any]]:
    """Fetch OrderFilled logs (topic0-filtered) across all *addresses*, concatenated."""
    out: list[dict[str, Any]] = []
    for address in addresses:
        out.extend(
            _rpc_get_logs(rpc_url, address, from_block, to_block, topics=[TOPIC0_ORDERFILLED])
        )
    return out


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
