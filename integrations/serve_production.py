"""
Real production entry point -- run this instead of `python webhook_server.py`
for anything beyond local testing. Flask's own dev server (what
`webhook_server.py`'s __main__ block uses) is explicitly not meant for
production: it's single-threaded by default and has no protection
against slow/malicious clients holding a worker open.

waitress, not gunicorn: this needs to run on the same Windows machine
that has the Pervasive ODBC driver for SOURCE_BACKEND=pervasive to
work, and gunicorn doesn't run on Windows at all (it depends on the
Unix-only fcntl module). waitress is pure Python and works the same on
Windows, Mac, or Linux.

Still binds to 127.0.0.1 only, same as webhook_server.py's own dev
server -- this is never meant to be reachable directly from the
internet. A real reverse proxy (see deploy/Caddyfile) sits in front of
this, terminates TLS, and forwards to this port -- that's what Telnyx's
webhook URL should actually point at, not this port directly.

Run: python integrations/serve_production.py
"""
from waitress import serve

from webhook_server import app

HOST = "127.0.0.1"
PORT = 5000
THREADS = 4  # waitress's own concurrency knob -- one request per real client action (an SMS or a voice tool call) is never a heavy workload, 4 is plenty at this scale

if __name__ == "__main__":
    print(f"Serving on http://{HOST}:{PORT} via waitress ({THREADS} threads)")
    print("This should sit behind a reverse proxy (see deploy/Caddyfile) -- never expose this port directly.")
    serve(app, host=HOST, port=PORT, threads=THREADS)
