# Schwab dashboard

A single page, served from your own computer, that shows what is in your Schwab accounts
and every request it sent to Schwab to get it.

It shows: connection and sign-in status, total value, today's change, cash, positions per
account, a watchlist, orders from the last 7 days, market hours, and an activity log.

## Try it without an account

```bash
pip install -e .
```

```bash
python -m dashboard --demo
```

This opens the page with made-up data. Nothing is sent to Schwab.

## Connect your Schwab account

1. Create an app at <https://developer.schwab.com> with callback URL `https://127.0.0.1`
   and wait until its status is "Ready For Use".
2. Save the app key and secret (typed hidden, stored in `~/.schwabdev/env.json`, readable only by you):

   ```bash
   python -m dashboard --setup
   ```

3. Optional but recommended: encrypt the saved sign-in tokens. Generate a key once and keep it
   somewhere safe (a password manager); the dashboard reads it from `SCHWABDEV_ENCRYPTION_KEY`.

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. Start it:

   ```bash
   python -m dashboard
   ```

   The first time, Schwab asks you to sign in in the browser; paste the address you are sent to
   back into the terminal. Then open the private link the terminal prints.

Schwab sign-ins last 7 days. When yours expires the page says so; stop the dashboard (Ctrl+C)
and start it again to sign in.

Options: `--port 8765`, `--symbols SPY,AAPL`, `--tokens-db PATH`, `--no-browser`.
`SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET` and `SCHWAB_CALLBACK_URL` override the saved credentials.

## How it is kept safe

- **Read-only.** It only looks up balances, positions, order history, quotes and market hours.
  There is no code path that places, changes or cancels an order.
- **Local only.** The server listens on `127.0.0.1`, so other devices cannot reach it.
- **Private link.** Data requests need a random token that changes every start. Requests from
  other websites (wrong `Host` or `Origin`) are refused.
- **No secrets in the browser.** The app key, app secret, tokens and account hashes stay in the
  Python process. Account numbers are masked to their last four digits.
- **Nothing loaded from the internet.** The page uses no external scripts, fonts or trackers and
  is served with a strict Content-Security-Policy.

## Files

| File | Role |
|---|---|
| `__main__.py` | Command line: `--setup`, `--demo`, start-up |
| `server.py` | Loopback-only web server and access checks |
| `data.py` | Calls the Schwab API through `schwabdev.Client` and shapes the results |
| `demo.py` | Made-up responses for `--demo` |
| `static/` | The page (HTML, CSS, JavaScript) |
