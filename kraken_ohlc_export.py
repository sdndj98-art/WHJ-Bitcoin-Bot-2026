"""Export completed public Kraken OHLC candles to a JSON array for offline research.

This helper uses only Kraken's public OHLC endpoint. It does not access private
account data or submit orders. Kraken currently limits OHLC history to its
most recent 720 rows; the still-forming candle is excluded.
"""
import argparse
import json
import math
import os
import tempfile
import time
import urllib.parse
import urllib.request


def fetch_completed_ohlc(pair="XBTUSD", interval_minutes=60, timeout=15,
                         as_of_timestamp=None):
    if not isinstance(pair, str) or not pair.strip() or len(pair) > 32:
        raise ValueError("pair must be a non-empty Kraken pair identifier")
    if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int):
        raise ValueError("interval_minutes must be an integer")
    if interval_minutes not in (1, 5, 15, 30, 60, 240, 1440, 10080, 21600):
        raise ValueError("unsupported Kraken OHLC interval")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive")
    as_of = time.time() if as_of_timestamp is None else as_of_timestamp
    if isinstance(as_of, bool) or not isinstance(as_of, (int, float)) or not math.isfinite(as_of) or as_of < 0:
        raise ValueError("as_of_timestamp must be finite and non-negative")

    query = urllib.parse.urlencode({"pair": pair.strip(), "interval": interval_minutes})
    request = urllib.request.Request(
        "https://api.kraken.com/0/public/OHLC?" + query,
        headers={"User-Agent": "WHJ-CVD-Research/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("error"):
        errors = payload.get("error", []) if isinstance(payload, dict) else ["invalid response"]
        raise RuntimeError("Kraken OHLC error: " + ", ".join(map(str, errors)))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Kraken OHLC response is missing result")
    keys = [key for key in result if key != "last"]
    if len(keys) != 1 or not isinstance(result[keys[0]], list):
        raise ValueError("Kraken OHLC response must contain exactly one pair row list")

    interval_seconds = interval_minutes * 60
    candles = []
    for row in result[keys[0]]:
        if not isinstance(row, (list, tuple)) or len(row) < 8:
            raise ValueError("Kraken returned a malformed OHLC row")
        start = int(float(row[0]))
        if start + interval_seconds <= as_of:
            candles.append([
                start, float(row[1]), float(row[2]), float(row[3]),
                float(row[4]), float(row[5]), float(row[6]), int(float(row[7])),
            ])
    candles.sort(key=lambda item: item[0])
    if len(candles) < 500:
        raise ValueError(
            f"only {len(candles)} completed candles available; "
            "the CVD research lab requires at least 500 contiguous candles"
        )
    for previous, current in zip(candles, candles[1:]):
        if current[0] - previous[0] != interval_seconds:
            raise ValueError("Kraken OHLC history contains a gap; refusing to export")
    return candles


def write_json_atomic(path, payload):
    target = os.path.abspath(path)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".whj-ohlc-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export at least 500 completed contiguous Kraken OHLC candles.")
    parser.add_argument("--pair", default="XBTUSD")
    parser.add_argument("--interval-minutes", type=int, default=60)
    parser.add_argument("--output", default="state/kraken_btc_usd_1h.json")
    parser.add_argument("--as-of", type=float, default=None, help="Optional Unix timestamp; defaults to current system time")
    args = parser.parse_args(argv)
    candles = fetch_completed_ohlc(args.pair, args.interval_minutes, as_of_timestamp=args.as_of)
    write_json_atomic(args.output, candles)
    print(json.dumps({
        "status": "OHLC_EXPORTED",
        "output": args.output,
        "sample_count": len(candles),
        "first_candle_unix": candles[0][0],
        "last_candle_unix": candles[-1][0],
        "interval_minutes": args.interval_minutes,
        "completed_only": True,
        "contiguous": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
