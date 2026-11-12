"""Single-instance supervisor for the read-only Kraken CVD collector.

Designed for Linux/Android Termux. Holds an advisory flock for the full
collector lifetime and forwards termination signals. No exchange order APIs.
"""
import argparse
import fcntl
import os
import signal
import subprocess
import sys
from pathlib import Path


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run one supervised, read-only Kraken public trade collector."
    )
    parser.add_argument("--pair", default="BTC/USD")
    parser.add_argument("--state-file", default="state/kraken_cvd_btc_usd.json")
    parser.add_argument("--trade-log", default="state/kraken_btc_usd_trades.jsonl")
    parser.add_argument("--checkpoint-file", default=None)
    parser.add_argument("--lock-file", default="state/kraken_cvd_btc_usd.lock")
    parser.add_argument("--max-trade-log-mb", type=int, default=250)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--initial-backoff", type=float, default=1.0)
    parser.add_argument("--max-backoff", type=float, default=30.0)
    parser.add_argument("--max-reconnect-attempts", type=int, default=0)
    return parser


def acquire_single_instance_lock(path):
    """Return an open, exclusively locked file handle or raise RuntimeError."""
    if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
        raise ValueError("lock path must be non-empty")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = open(target, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError("Kraken CVD collector is already running (lock is held)") from exc
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()) + "\n")
    handle.flush()
    return handle


def build_collector_command(args):
    """Build an explicit argument vector; never invoke a shell."""
    command = [
        sys.executable, str(Path(__file__).with_name("kraken_cvd_collector.py")),
        "--pair", args.pair,
        "--state-file", args.state_file,
        "--trade-log", args.trade_log,
        "--max-trade-log-mb", str(args.max_trade_log_mb),
        "--timeout", str(args.timeout),
        "--initial-backoff", str(args.initial_backoff),
        "--max-backoff", str(args.max_backoff),
        "--max-reconnect-attempts", str(args.max_reconnect_attempts),
    ]
    if args.checkpoint_file:
        command.extend(["--checkpoint-file", args.checkpoint_file])
    return command


def main(argv=None):
    args = build_parser().parse_args(argv)
    lock_handle = None
    child = None
    previous_handlers = {}

    try:
        lock_handle = acquire_single_instance_lock(args.lock_file)
        command = build_collector_command(args)
        child = subprocess.Popen(command)

        def forward_signal(signum, _frame):
            if child is not None and child.poll() is None:
                child.send_signal(signum)

        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward_signal)

        return child.wait()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        if lock_handle is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
