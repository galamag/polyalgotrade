from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import structlog


def configure_logging(mode: str) -> Any:
    """Configure structlog for JSON output and return a bound logger.

    Args:
        mode: One of 'backtest', 'paper', or 'live'.  Bound to every log
              record so we can always tell which execution context emitted it.
    """
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ]
    )
    return structlog.get_logger().bind(mode=mode)


class TradeJournal:
    """Append-only JSONL trade journal (logging-observability.md, ADR 0004).

    Every order, fill, and decision is recorded with full context so we can
    always reconstruct *why* the bot acted. Fields required on every record:
    ``ts``, ``mode``, ``corr_id``.  Callers supply domain fields (``event``,
    ``reason``, ``fee``, ``strategy``, etc.).
    """

    def __init__(self, path: Path, mode: str, corr_id: str) -> None:
        self.path = Path(path)
        self.mode = mode
        self.corr_id = corr_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, **fields: Any) -> None:
        """Append one JSON line to the journal.

        The timestamp (``ts``) is Unix milliseconds — sortable, unambiguous,
        and cheap.  ``default=str`` on ``json.dumps`` ensures any non-standard
        type (Decimal, Enum, Pydantic model) serialises without crashing.
        """
        row: dict[str, Any] = {
            "ts": int(time.time() * 1000),
            "mode": self.mode,
            "corr_id": self.corr_id,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
