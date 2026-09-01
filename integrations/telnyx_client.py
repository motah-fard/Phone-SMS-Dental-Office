"""
Thin wrapper around Telnyx's Messaging API. Needs a real TELNYX_API_KEY
and TELNYX_PHONE_NUMBER once the account/BAA exist -- nothing here can
be tested until then. Kept deliberately small: one function to send a
message, matching exactly what sms_conversation.py needs.

Retries ONLY transient failures (network errors, timeouts, and HTTP
429/5xx -- Telnyx's own infrastructure being briefly unavailable or
rate-limiting), with a short exponential backoff. A 4xx response (bad
auth, malformed request, invalid phone number) is never retried --
retrying an already-wrong request just wastes time and won't ever
succeed. This is a deliberate distinction, not an oversight: the LLM
SDKs (anthropic/openai) already do this same transient-vs-permanent
distinction internally, which is why they don't get a second retry
layer wrapped around them here (see llm_fallback.py's docstring).

Requires: pip install requests
"""
import os
import time

import requests

TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY")
TELNYX_PHONE_NUMBER = os.environ.get("TELNYX_PHONE_NUMBER")
TELNYX_MESSAGES_URL = "https://api.telnyx.com/v2/messages"
REQUEST_TIMEOUT_SECONDS = 10

MAX_RETRIES = 2  # up to 3 total attempts
RETRY_BACKOFF_SECONDS = 1  # doubles each retry: 1s, then 2s
TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


class TelnyxError(Exception):
    """Raised for any failure sending via Telnyx -- missing credentials,
    a non-transient error, or a transient error that exhausted all
    retries. Callers should catch this specifically rather than letting
    requests' own exception types leak into webhook_server.py's error
    handling."""


def send_sms(to_phone: str, body: str) -> dict:
    if not TELNYX_API_KEY or not TELNYX_PHONE_NUMBER:
        raise TelnyxError(
            "TELNYX_API_KEY / TELNYX_PHONE_NUMBER not set -- can't send for real yet, "
            "this needs the Telnyx account + BAA in place first."
        )

    last_exception = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                TELNYX_MESSAGES_URL,
                headers={"Authorization": f"Bearer {TELNYX_API_KEY}"},
                json={"from": TELNYX_PHONE_NUMBER, "to": to_phone, "text": body},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            # The request never got a response at all -- genuinely transient.
            last_exception = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * (2 ** attempt))
                continue
            raise TelnyxError(f"failed to send SMS via Telnyx after {MAX_RETRIES + 1} attempts: {e}") from e

        if response.status_code in TRANSIENT_HTTP_STATUS_CODES and attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * (2 ** attempt))
            continue

        try:
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            # Either a non-transient 4xx (never retry -- it'll never
            # succeed) or a transient one that already used up its
            # retries above.
            raise TelnyxError(f"failed to send SMS via Telnyx: {e}") from e

    raise TelnyxError(  # pragma: no cover -- unreachable: every path above returns or raises on the last attempt
        f"failed to send SMS via Telnyx after {MAX_RETRIES + 1} attempts: {last_exception}"
    )
