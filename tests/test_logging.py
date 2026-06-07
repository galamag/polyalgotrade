import json

from pat.logging import TradeJournal, configure_logging


def test_journal_appends_jsonl_with_required_fields(tmp_path):
    p = tmp_path / "journal.jsonl"
    j = TradeJournal(p, mode="backtest", corr_id="run-1")
    j.record(event="order", strategy="mm", reason="quote",
             price="0.40", fee="0.0175", token_id="t1")
    line = json.loads(p.read_text().splitlines()[0])
    for k in ("ts", "event", "mode", "strategy", "reason", "corr_id", "fee"):
        assert k in line
    assert line["mode"] == "backtest" and line["corr_id"] == "run-1"


def test_journal_appends_multiple_lines(tmp_path):
    p = tmp_path / "j.jsonl"
    j = TradeJournal(p, mode="paper", corr_id="r2")
    j.record(event="order", reason="a")
    j.record(event="fill", reason="b")
    assert len(p.read_text().splitlines()) == 2


def test_configure_logging_returns_logger():
    assert configure_logging(mode="backtest") is not None
