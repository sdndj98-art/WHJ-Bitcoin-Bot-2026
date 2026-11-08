"""Append-only, bounded JSONL journal for normalized Kraken trade events."""
import json
import os

from kraken_order_flow import _trade_event_timestamp_ns


class TradeJournalError(RuntimeError):
    """Raised when raw trade history cannot be safely persisted."""


class JsonlTradeJournal:
    """Durable per-symbol trade journal; refuses gaps and corrupt prior lines."""

    def __init__(self, path, max_bytes=250 * 1024 * 1024):
        if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
            raise ValueError("journal path must be non-empty")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        self.path = os.fspath(path)
        self.max_bytes = max_bytes
        self.last_trade_id = None
        self.last_timestamp_ns = None
        self.symbol = None
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        self._restore()

    def _restore(self):
        try:
            handle = open(self.path, "rb")
        except FileNotFoundError:
            return
        with handle:
            for line_number, raw in enumerate(handle, 1):
                if not raw.endswith(b"\n"):
                    raise TradeJournalError(
                        f"journal has an incomplete final line at {line_number}"
                    )
                try:
                    event = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise TradeJournalError(
                        f"journal contains invalid JSON at line {line_number}"
                    ) from exc
                if not isinstance(event, dict):
                    raise TradeJournalError("journal lines must contain JSON objects")
                trade_id = event.get("trade_id")
                if isinstance(trade_id, bool) or not str(trade_id).isdigit() or int(trade_id) <= 0:
                    raise TradeJournalError("journal contains an invalid trade ID")
                trade_id = int(trade_id)
                symbol = event.get("symbol")
                if not isinstance(symbol, str) or not symbol.strip():
                    raise TradeJournalError("journal contains an invalid symbol")
                symbol = symbol.strip()
                if self.symbol is not None and symbol != self.symbol:
                    raise TradeJournalError("journal contains mixed symbols")
                self.symbol = symbol
                timestamp_ns = _trade_event_timestamp_ns(event.get("timestamp"))
                if self.last_trade_id is not None and trade_id != self.last_trade_id + 1:
                    raise TradeJournalError("journal trade IDs are not strictly contiguous")
                if self.last_timestamp_ns is not None and timestamp_ns < self.last_timestamp_ns:
                    raise TradeJournalError("journal timestamps move backwards")
                self.last_trade_id = trade_id
                self.last_timestamp_ns = timestamp_ns
        if os.path.getsize(self.path) > self.max_bytes:
            raise TradeJournalError("existing trade journal exceeds configured size limit")

    def append(self, events):
        if not isinstance(events, (list, tuple)):
            raise ValueError("events must be a list or tuple")
        normalized = {}
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("each event must be an object")
            trade_id = event.get("trade_id")
            if isinstance(trade_id, bool) or not str(trade_id).isdigit() or int(trade_id) <= 0:
                raise ValueError("trade_id must be a positive integer")
            trade_id = int(trade_id)
            timestamp_ns = _trade_event_timestamp_ns(event.get("timestamp"))
            price = float(event.get("price"))
            qty = float(event.get("qty"))
            side = event.get("side")
            symbol = event.get("symbol")
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("symbol must be a non-empty string")
            symbol = symbol.strip()
            if self.symbol is not None and symbol != self.symbol:
                raise TradeJournalError("trade event symbol does not match journal")
            if price <= 0 or qty <= 0 or side not in ("buy", "sell"):
                raise ValueError("invalid normalized trade event")
            item = {
                "trade_id": trade_id, "timestamp": event.get("timestamp"),
                "price": price, "qty": qty, "side": side, "symbol": symbol,
            }
            if trade_id in normalized and normalized[trade_id] != item:
                raise ValueError("conflicting events share a trade ID")
            normalized[trade_id] = item

        pending = []
        batch_symbol = self.symbol
        next_id = self.last_trade_id
        next_timestamp_ns = self.last_timestamp_ns
        for trade_id in sorted(normalized):
            event = normalized[trade_id]
            if batch_symbol is None:
                batch_symbol = event["symbol"]
            elif event["symbol"] != batch_symbol:
                raise TradeJournalError("trade batch contains mixed symbols")
            timestamp_ns = _trade_event_timestamp_ns(event["timestamp"])
            if next_id is not None and trade_id <= next_id:
                continue
            if next_id is not None and trade_id != next_id + 1:
                raise TradeJournalError(
                    f"raw trade journal gap: expected {next_id + 1}, received {trade_id}"
                )
            if next_timestamp_ns is not None and timestamp_ns < next_timestamp_ns:
                raise TradeJournalError("raw trade timestamp moved backwards")
            pending.append(event)
            next_id = trade_id
            next_timestamp_ns = timestamp_ns

        if not pending:
            return {"status": "UNCHANGED", "appended": 0, "last_trade_id": self.last_trade_id}
        payload = b"".join(
            (json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            for item in pending
        )
        current_size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        if current_size + len(payload) > self.max_bytes:
            raise TradeJournalError("trade journal size limit reached; collector must stop")
        try:
            with open(self.path, "ab") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise TradeJournalError("failed to durably append raw trade events") from exc
        self.last_trade_id = next_id
        self.last_timestamp_ns = next_timestamp_ns
        self.symbol = batch_symbol
        return {
            "status": "OK", "appended": len(pending),
            "last_trade_id": self.last_trade_id,
        }
