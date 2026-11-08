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

## Generate an analysis snapshot and MT5 paper ledger

From the Windows project folder, with the terminal open and signed in to a demo account:

```powershell
python mt5_snapshot.py --symbol BTCUSD --bars 300 --output mt5_snapshot.json --update-paper-ledger
```

Use the exact broker symbol (for example, `BTCUSD.a`, `BTCUSDm`, or `XAUUSD`).
The snapshot reads 1h, 4h, and 6h completed candles, computes the WHJ scanner
diagnostics, and stores only the market quote/candles and paper-account summaries.
It deliberately excludes account login, broker server, balance, and equity.

Then open the WHJ dashboard and import `mt5_snapshot.json` in the **منصة MT5**
section. Importing is local to that browser tab; the snapshot is not uploaded to
GitHub Pages or any server.

The optional `--update-paper-ledger` flag updates five independent **virtual**
paper accounts using BTC/XBT 1h candles. State is stored locally in
`mt5_paper_state/`, separate from the existing Termux/GitHub crypto paper ledgers.
The first run warms the ledgers from history; subsequent runs process each new
closed candle once. Do not delete or edit the state files to reset a ledger.

For a non-BTC symbol, omit `--update-paper-ledger`; the scanner still reports
research diagnostics, but the BTC-specific paper portfolio is intentionally blocked.

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

The broker connector is **read-only**. It deliberately has no `order_send`,
position-closing, or money-transfer method. The optional paper ledger is virtual and
uses broker candles only; it does not place orders in an MT5 demo account or a live account. It does not activate live trading,
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


## Optional demo-only order gateway prototype

WHJ also contains a separate manual demo-order gateway described in
[MT5_DEMO_EXECUTION.md](MT5_DEMO_EXECUTION.md). It is not connected to the scanner,
local paper ledger, dashboard or scheduled jobs. It requires both an in-code opt-in
and the local environment variable `WHJ_ENABLE_MT5_DEMO_ORDERS=YES`, and it rejects
any account not positively identified by the MT5 API as a demo account. It is a
controlled integration prototype, not an autonomous strategy or live-trading feature.
