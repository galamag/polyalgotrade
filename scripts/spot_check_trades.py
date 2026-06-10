"""On-chain spot-check of data-api /trades rows (claim I13 trust step).

POINT lookups only: eth_getTransactionReceipt per saved trade's transactionHash.
NEVER range getLogs here — that exploded on active wallets (ADR 0020). Hard cap
_MAX_RECEIPTS per run is the CU rail (~40 x 15 CU ~ 600 CU ~ $0.0003 on Alchemy PAYG).

Reads POLYGON_RPC_URL from the environment (or --rpc-url). Report-only: prints a
match-rate per wallet; the human upgrades claim I13 in docs/research/claims-verification.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import httpx  # noqa: E402
import structlog  # noqa: E402

from pat.data.polymarket_history import price_and_size  # noqa: E402
from pat.data.polymarket_on_chain import decode_v2_orderfilled  # noqa: E402

log = structlog.get_logger(__name__)

_MAX_RECEIPTS = 40  # hard CU rail per run
_PRICE_TOL = Decimal("0.005")  # data-api rounds; on-chain is 6-dp fixed point
_SIZE_TOL = Decimal("0.01")
_REQUEST_TIMEOUT = 30  # seconds


def _rpc_get_receipt(rpc_url: str, tx_hash: str) -> dict[str, Any]:
    """eth_getTransactionReceipt. The ONLY wire-touching function — monkeypatch in tests."""
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_getTransactionReceipt", "params": [tx_hash],
    }
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.post(rpc_url, json=payload)
        response.raise_for_status()
        body = response.json()
    if "error" in body:
        raise RuntimeError(f"JSON-RPC error: {body['error']}")
    result: dict[str, Any] = body["result"]
    return result


def _row_matches_log(wallet: str, trade: dict[str, Any], dec: dict[str, Any]) -> bool:
    """One decoded OrderFilled log vs one data-api row: asset, role, side, price, size."""
    if dec["tokenId"] != str(trade["asset"]):
        return False
    w = wallet.lower()
    is_maker = dec["maker"].lower() == w
    is_taker = dec["taker"].lower() == w
    if not (is_maker or is_taker):
        return False
    maker_buys = int(dec["side"]) == 0
    wallet_buys = maker_buys if is_maker else (not maker_buys)
    row_buys = str(trade["side"]).upper() == "BUY"
    if wallet_buys != row_buys:
        return False
    price, size = price_and_size(dec)
    return (
        abs(price - Decimal(str(trade["price"]))) <= _PRICE_TOL
        and abs(size - Decimal(str(trade["size"]))) <= _SIZE_TOL
    )


def check_wallet(
    wallet: str,
    trades: list[dict[str, Any]],
    rpc_url: str,
    *,
    n_sample: int = 15,
    get_receipt: Any = None,
) -> dict[str, Any]:
    """Sample the most recent *n_sample* rows; verify each against its tx receipt."""
    gr = get_receipt or _rpc_get_receipt
    sample = sorted(trades, key=lambda t: int(str(t["timestamp"])), reverse=True)
    sample = sample[: min(n_sample, _MAX_RECEIPTS)]

    receipt_cache: dict[str, dict[str, Any]] = {}
    matched = 0
    mismatches: list[dict[str, Any]] = []
    n_checked = 0
    for t in sample:
        tx = str(t["transactionHash"])
        if tx not in receipt_cache:
            if len(receipt_cache) >= _MAX_RECEIPTS:
                log.warning("spot_check.receipt_cap_hit", cap=_MAX_RECEIPTS)
                break
            receipt_cache[tx] = gr(rpc_url, tx)
        n_checked += 1
        decoded = []
        for lg in receipt_cache[tx].get("logs", []):
            if not lg.get("topics"):
                continue
            d = decode_v2_orderfilled(lg)
            if d is not None:
                decoded.append(d)
        if any(_row_matches_log(wallet, t, d) for d in decoded):
            matched += 1
        else:
            mismatches.append({"tx": tx, "asset": t["asset"], "side": t["side"],
                               "price": t["price"], "size": t["size"]})
    return {
        "wallet": wallet, "n_checked": n_checked, "n_matched": matched,
        "mismatches": mismatches,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Spot-check data-api /trades vs on-chain receipts (I13 trust step)."
    )
    p.add_argument("--trades-dir", type=Path, default=Path("data/raw/wallet_trades"))
    p.add_argument(
        "--wallets", nargs="*", default=None,
        help="Addresses to check (default: first winner + first control).",
    )
    p.add_argument("--n-sample", type=int, default=15)
    p.add_argument("--rpc-url", default=os.environ.get("POLYGON_RPC_URL", ""))
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
    if not args.rpc_url:
        print("POLYGON_RPC_URL not set and --rpc-url missing")  # noqa: T201
        sys.exit(2)
    wallets = args.wallets
    if not wallets:
        winners = json.loads(
            (args.trades_dir / "_winners.json").read_text(encoding="utf-8"))
        control = json.loads(
            (args.trades_dir / "_control.json").read_text(encoding="utf-8"))
        wallets = [winners[0], control[0]]
    for w in wallets:
        rows = json.loads((args.trades_dir / f"{w}.json").read_text(encoding="utf-8"))
        res = check_wallet(w, rows, args.rpc_url, n_sample=args.n_sample)
        rate = res["n_matched"] / res["n_checked"] if res["n_checked"] else 0.0
        log.info("spot_check.result", wallet=w, n_checked=res["n_checked"],
                 n_matched=res["n_matched"], match_rate=round(rate, 3))
        print(f"{w}: {res['n_matched']}/{res['n_checked']} matched "  # noqa: T201
              f"({rate:.0%}); mismatches: {res['mismatches']}")
