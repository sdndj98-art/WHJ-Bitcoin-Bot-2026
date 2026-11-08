# MT5 demo execution gateway — guarded prototype

This is a **demo-account-only** execution gateway. It is not connected to the scanner,
dashboard, scheduled jobs, or any live strategy. The default remains disabled.

## Two separate opt-ins

The calling Python code must instantiate the gateway with `enabled=True`, and the
local Windows environment must separately contain:

```powershell
$env:WHJ_ENABLE_MT5_DEMO_ORDERS = "YES"
```

If either opt-in is absent, execution is blocked. The gateway then independently
checks the MT5 API's `ACCOUNT_TRADE_MODE_DEMO` value. Real, contest, or unknown
account modes are rejected even when both opt-ins are present.

## Mandatory protections

- A unique `signal_id` is required. A local SQLite guard reserves it before sending;
  duplicate IDs are blocked, including after an ambiguous timeout.
- Only market BUY/SELL orders are supported. Position closing, modification,
  withdrawals and transfers are not implemented.
- Both stop-loss and take-profit are mandatory and checked against direction,
  broker tick size, minimum stop distance, volume minimum/maximum/step and filling policy.
- `order_check` must approve the request before `order_send`.
- No automatic retry is made. Unknown or partial outcomes require manual reconciliation
  in the MT5 demo terminal before a new signal is considered.
- No login, password or account number is accepted by this module.
- The local SQLite guard file is private runtime state and must never be committed.

## Important limitation

This gateway is a guarded, manual demo execution primitive for controlled integration
tests. It is not yet wired to scanner signals or an autonomous trade manager, and it
must not be used with a live account. Verify the exact broker's symbol contract,
commission, margin, stop levels, execution mode and demo fills before extending it.
