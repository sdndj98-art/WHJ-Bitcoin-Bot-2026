# MetaTrader 5 connector (read-only first)

WHJ now includes an optional Python adapter for MetaTrader 5. It is intentionally
separate from the Kraken/Coinbase crypto data paths and the existing paper ledgers.

## Runtime requirements

- Run the connector on Windows with the MetaTrader 5 desktop terminal installed.
- Install the official MetaTrader5 Python package in that Windows Python environment:
  `python -m pip install MetaTrader5`
- Open the terminal and sign in to a **demo account** first. The adapter attaches to
  the already configured terminal; it does not accept or store account passwords.
- The adapter can report broker/server/account summary, validated bid/ask quotes,
  and completed OHLCV candles for broker symbols such as BTCUSD, XAUUSD, or FX pairs.
  Exact symbol names and availability depend on the broker.
- MT5 candle position 0 is the forming candle. WHJ requests from position 1 so only
  completed candles are returned.

## Safe usage

```python
from mt5_adapter import MetaTrader5ReadOnly

mt5 = MetaTrader5ReadOnly()
try:
    print(mt5.connect())
    print(mt5.get_quote("BTCUSD"))
    candles = mt5.fetch_closed_rates("BTCUSD", "TIMEFRAME_H1", 500)
    print(candles[-1])
finally:
    mt5.close()
```

This first integration is **read-only**. It deliberately has no `order_send`,
position-closing, or money-transfer method. It does not activate live trading,
change the terminal's permissions, or store credentials. A terminal may report that
trading is allowed by its broker; WHJ still does not submit orders.

## Platform boundary

The official MetaTrader5 Python package is intended for Windows terminals. Termux /
Android and GitHub's Linux-hosted workflows cannot run this connector directly.
Keep the existing Termux analysis workflow unchanged; run the MT5 connector on a
Windows workstation or Windows VPS, then integrate its validated market data with
WHJ's shared analysis/paper layer. A later, separately reviewed execution adapter
would require demo-account testing, idempotent order handling, broker volume/stop
constraints, reconciliation, and explicit live-trading controls before any real order
could be enabled.
