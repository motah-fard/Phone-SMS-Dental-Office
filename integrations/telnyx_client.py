"""
Thin wrapper around Telnyx's Messaging API. Needs a real TELNYX_API_KEY
and TELNYX_PHONE_NUMBER once the account/BAA exist -- nothing here can
be tested until then. Kept deliberately small: one function to send a
message, matching exactly what sms_conversation.py needs.

Requires: pip install requests
"""
import os
import requests

TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY")
TELNYX_PHONE_NUMBER = os.environ.get("TELNYX_PHONE_NUMBER")
TELNYX_MESSAGES_URL = "https://api.telnyx.com/v2/messages"


def send_sms(to_phone: str, body: str) -> dict:
    if not TELNYX_API_KEY or not TELNYX_PHONE_NUMBER:
        raise RuntimeError(
            "TELNYX_API_KEY / TELNYX_PHONE_NUMBER not set -- can't send for real yet, "
            "this needs the Telnyx account + BAA in place first."
        )
    response = requests.post(
        TELNYX_MESSAGES_URL,
        headers={"Authorization": f"Bearer {TELNYX_API_KEY}"},
        json={"from": TELNYX_PHONE_NUMBER, "to": to_phone, "text": body},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
