# Running WHJ Bitcoin Bot on Termux

This project is read-only with respect to exchanges. It retrieves public market data and performs analysis and hypothetical paper simulations. It does not submit exchange orders and does not need exchange API keys.

## 1. Prepare Termux

Run:

```bash
pkg update -y
pkg upgrade -y
pkg install python git gh -y
```

Check the tools:

```bash
python --version
git --version
gh --version
```

Python 3.10 or newer is required. If the Python version is older, update Termux packages before continuing.

## 2. Open the project

```bash
cd ~/WHJ-Bitcoin-Bot-2026
```

If the project is not present yet, clone it once:

```bash
git clone https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026.git
cd WHJ-Bitcoin-Bot-2026
```

Do not clone over an existing project directory.

## 3. Run the read-only diagnostics

```bash
bash scripts/termux_check.sh
```

The check reports the Python version, required source files, Python compilation, unit-test results, Git remote status, and GitHub CLI authentication. It does not install packages, run the market-data fetch, modify paper-account ledgers, or place trades.

## 4. Update from GitHub safely

Before updating, inspect local changes:

```bash
git status --short --branch
```

If there are local changes, back them up and review them before switching branches or pulling. Do not use `git reset --hard`, `git clean -fd`, or overwrite paper-state JSON files as a troubleshooting shortcut.

To inspect and test the Termux maintenance branch:

```bash
git fetch origin
git switch --track origin/maintenance/termux-doctor-and-local-state-safety-20261108
bash scripts/termux_check.sh
```

If the branch already exists locally, use `git switch maintenance/termux-doctor-and-local-state-safety-20261108` instead.

## 5. Local runtime data

Generated reports and persistent paper-ledger JSON files are local runtime data and are now listed in `.gitignore` to reduce accidental commits. Ignoring a file does not delete it. Files already tracked by Git remain tracked until deliberately changed in a reviewed commit.

Keep backups of paper-ledger files. Never share GitHub tokens, passwords, Telegram tokens, or other credentials in chat or commit them to the repository.

## 6. Run the application

Only after the diagnostics and tests pass:

```bash
python main.py
python dashboard.py
```

These commands can fetch public market data and generate local reports. They remain analysis/paper-only. The dashboard is a report viewer, not an exchange execution interface.

## Troubleshooting

- `python: command not found`: run `pkg install python`.
- `git: command not found`: run `pkg install git`.
- `gh: command not found`: run `pkg install gh`.
- GitHub login issue: run `gh auth login`; never paste the displayed token or device code into chat.
- Network or DNS errors: check Android connectivity, then retry. Do not repeatedly reset Git or delete local state.
- Test failure: keep the full failing test name and traceback; do not run the application to work around a failing test.

## MetaTrader 5 compatibility

The optional MT5 connector does not run directly in Termux/Android. It requires a Windows workstation or Windows VPS with the MetaTrader 5 desktop terminal and official Python package. Follow [MT5_SETUP.md](MT5_SETUP.md) on that Windows machine. The Termux workflow remains the existing read-only crypto analysis and paper-trading environment; it does not need MT5 credentials or packages.
