# Running this for real (not local testing)

## What changed from local testing

- `python integrations/webhook_server.py` (Flask's own dev server) is
  for local testing only -- single-threaded, no protection against a
  slow/stuck connection holding a worker open.
- `python integrations/serve_production.py` runs the same Flask app
  through **waitress** instead -- a real production-grade WSGI server.
  Chosen specifically because it's pure Python and works on Windows;
  gunicorn (the more commonly recommended choice) does not run on
  Windows at all.
- Conversation state (`integrations/conversation_store.py`) is already
  SQLite-backed, not in-memory -- survives a restart and works
  correctly even if you ever run more than one server process.

## Steps

1. **Start the app server:**
   ```
   python integrations/serve_production.py
   ```
   This binds to `127.0.0.1:5000` only -- deliberately not reachable
   from the internet directly.

2. **Put a real reverse proxy with TLS in front of it.** See
   `deploy/Caddyfile` -- fill in your real domain, point that domain's
   DNS at this server's public IP, then run:
   ```
   caddy run --config deploy/Caddyfile
   ```
   Caddy handles getting and renewing a real Let's Encrypt certificate
   automatically from just the domain name in that file.

3. **Point Telnyx at the real HTTPS domain**, never at
   `127.0.0.1:5000` directly:
   - SMS webhook: `https://your-domain.example.com/webhooks/telnyx/sms`
   - Voice assistant tools: `https://your-domain.example.com/tools/*`

## Still manual, not something a config file can do

- **Encryption at rest** for `mirror.db`, `identity_lookup.db`,
  `audit_log.db`, `conversation_state.db` -- enable BitLocker (or
  equivalent) on the actual machine's disk. No code change makes this
  happen; it's an OS-level setting on the real server.
- **File permissions** on those same database files -- restrict them to
  only the account this server runs as.
- **Keeping the server running** (a Windows service, or Task Scheduler
  entry, or equivalent) so it survives a reboot without someone having
  to manually restart it.

## Running it as a background/persistent process on Windows

The simplest option for keeping `serve_production.py` running is
**NSSM** (Non-Sucking Service Manager) -- wraps any command as a real
Windows service that starts on boot and restarts if it crashes:

```
nssm install DentalPhoneServer "C:\path\to\python.exe" "C:\path\to\integrations\serve_production.py"
nssm start DentalPhoneServer
```

This is optional for early testing (running it in a terminal window is
fine while you're actively testing), but necessary before this is
something the practice relies on without you watching it.
