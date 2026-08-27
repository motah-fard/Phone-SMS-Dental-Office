"""
Flask app Telnyx calls into. Two jobs:

1. /webhooks/telnyx/sms -- receives inbound texts, runs them through
   sms_conversation.py, sends the reply back via telnyx_client.
2. /tools/* -- endpoints meant to be registered as "webhook tools" on a
   Telnyx AI Voice Assistant (see docs/telnyx_assistant_tools.md), so the
   voice AI can check availability / book / reschedule during a live
   call the same way the SMS path does.

Security, both required before this ever goes live (not optional
hardening -- these endpoints touch PHI):

- The SMS webhook verifies Telnyx's Ed25519 signature on every request.
  Without this, anyone who finds the URL could POST a fake inbound
  message and make the server send arbitrary texts through your Telnyx
  number, or probe patient data via the reply content.
- The /tools/* endpoints require a shared-secret header. These aren't
  covered by Telnyx's webhook signing scheme the same way, and without
  this check anyone with the URL could look up or reschedule any
  patient's appointment by guessing/knowing their phone number.

Error handling: every custom exception raised anywhere in book.py or
availability.py is caught here (or in sms_conversation.py for the SMS
path) and turned into a clean, non-leaking response -- a caller/texter
never sees a raw stack trace or database error message.

Nothing here can run for real without a Telnyx account + phone number +
webhook pointed at wherever this is hosted (needs real HTTPS -- a
reverse proxy in front of this, not Flask's dev server, for production).
State is in-memory only (fine for local testing, resets on restart --
swap for a real table before going live).

Requires: pip install flask requests pynacl
"""
import base64
import hmac
import os
import sys
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, request, jsonify
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "conversation"))

from sms_conversation import handle_inbound_sms
from telnyx_client import send_sms, TelnyxError
from book import (
    get_upcoming_appointments, reschedule_appointment, book_new_appointment,
    verify_patient, parse_dob, SchedulingError,
)
from availability import get_open_slots, find_soonest_slots_any_provider, AvailabilityError
from business_hours import is_staffed, next_staffed_description

app = Flask(__name__)

# phone -> conversation state dict. In-memory demo only.
_conversation_state: dict[str, dict] = {}


@app.errorhandler(KeyError)
@app.errorhandler(TypeError)
@app.errorhandler(ValueError)
def handle_malformed_request(error):
    """A missing/wrong-typed field in the request body raises one of
    these -- without this handler Flask would return an opaque 500.
    Catching it here keeps every route's body free of repetitive
    try/except while still failing cleanly on bad input."""
    return jsonify({"error": f"malformed request: {error}"}), 400


@app.errorhandler(SchedulingError)
@app.errorhandler(AvailabilityError)
def handle_backend_failure(error):
    """A database/availability failure inside book.py or availability.py.
    The real cause is already in the audit log (both modules log before
    raising) -- this response deliberately doesn't repeat it back to the
    caller, just a generic 'try again' signal."""
    return jsonify({"error": "temporarily unable to access scheduling data, please try again shortly"}), 503


TELNYX_PUBLIC_KEY = os.environ.get("TELNYX_PUBLIC_KEY")
TOOLS_SHARED_SECRET = os.environ.get("TOOLS_SHARED_SECRET")

WEBHOOK_MAX_AGE_SECONDS = 300  # reject anything older -- blocks replay of a captured valid request


def verify_telnyx_signature(raw_body: bytes, signature_header: str, timestamp_header: str) -> bool:
    """Telnyx signs webhooks with Ed25519. Verify against the public key
    from the Telnyx portal (Webhooks section) before trusting anything
    in the payload. Docs: https://developers.telnyx.com/docs/messaging/webhooks"""
    if not TELNYX_PUBLIC_KEY or not signature_header or not timestamp_header:
        return False
    try:
        if abs(time.time() - int(timestamp_header)) > WEBHOOK_MAX_AGE_SECONDS:
            return False
        verify_key = VerifyKey(base64.b64decode(TELNYX_PUBLIC_KEY))
        signed_payload = f"{timestamp_header}|".encode() + raw_body
        verify_key.verify(signed_payload, base64.b64decode(signature_header))
        return True
    except (BadSignatureError, ValueError):
        return False


def require_tools_secret(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not TOOLS_SHARED_SECRET:
            return jsonify({"error": "server misconfigured -- TOOLS_SHARED_SECRET not set"}), 500
        provided = request.headers.get("X-Internal-Tool-Secret", "")
        if not hmac.compare_digest(provided, TOOLS_SHARED_SECRET):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper


@app.route("/webhooks/telnyx/sms", methods=["POST"])
def telnyx_sms_webhook():
    raw_body = request.get_data()
    if not verify_telnyx_signature(
        raw_body,
        request.headers.get("telnyx-signature-ed25519"),
        request.headers.get("telnyx-timestamp"),
    ):
        return jsonify({"error": "invalid signature"}), 401

    payload = request.json["data"]["payload"]
    from_phone = payload["from"]["phone_number"]
    text = payload["text"]

    state = _conversation_state.get(from_phone, {})
    # handle_inbound_sms never raises (it catches its own backend errors
    # and returns a calm apology message instead) -- so no try/except
    # needed here for that. Sending the reply is a separate failure mode.
    reply, new_state = handle_inbound_sms(from_phone, text, state)
    _conversation_state[from_phone] = new_state

    try:
        send_sms(from_phone, reply)
    except TelnyxError as e:
        # The conversation logic already ran and state is saved -- the
        # patient just doesn't get this particular reply. Telnyx will
        # likely retry the inbound webhook if we return non-2xx, which
        # would re-run the conversation logic unexpectedly, so we still
        # return ok here but this failure needs real monitoring/alerting
        # before go-live, not just a print statement.
        print(f"[telnyx_sms_webhook] failed to send reply to {from_phone}: {e}")
        return jsonify({"status": "reply_send_failed"}), 200

    return jsonify({"status": "ok"})


# --- Voice AI Assistant tool endpoints (function-calling targets) ---
# `phone` must come from the call's verified caller-ID metadata on the
# Telnyx/assistant side, never from something the caller says out loud --
# otherwise anyone could claim to be a different patient's phone number
# and reach their appointment data. See docs/telnyx_assistant_tools.md.
#
# Every tool below that touches appointment data requires `dob` too --
# a phone call has no equivalent to SMS's "we already texted this exact
# info to this number" shortcut, so every voice call verifies phone +
# date of birth (book.verify_patient) before anything is disclosed or
# changed, full stop.

@app.route("/tools/verify_patient", methods=["POST"])
@require_tools_secret
def tool_verify_patient():
    """Call this first, once, at the start of a call. The assistant
    should ask for date of birth naturally (see conversation/voice_persona.md)
    and pass what the caller says here in dob (MM/DD/YYYY) -- this endpoint
    does the normalization and the actual match."""
    phone = request.json["phone"]
    dob = parse_dob(request.json["dob"])
    if dob is None:
        return jsonify({"verified": False, "error": "could not parse date of birth"}), 400
    patient = verify_patient(phone, dob, actor="voice_tool:verify_patient")
    if patient is None:
        return jsonify({"verified": False}), 404
    return jsonify({"verified": True, "first_name": patient["first_name"]})


@app.route("/tools/check_staffed_hours", methods=["POST"])
@require_tools_secret
def tool_check_staffed_hours():
    """Call this before ever offering to transfer to a live person.
    The assistant must never say it can connect the caller to staff
    when this returns staffed=false -- say when someone will follow up
    instead (next_available), never imply someone could pick up now."""
    return jsonify({"staffed": is_staffed(), "next_available": next_staffed_description()})


@app.route("/tools/get_upcoming_appointments", methods=["POST"])
@require_tools_secret
def tool_get_upcoming_appointments():
    phone = request.json["phone"]
    dob = parse_dob(request.json["dob"])
    if dob is None:
        return jsonify({"error": "could not parse date of birth"}), 400
    patient = verify_patient(phone, dob, actor="voice_tool:get_upcoming_appointments")
    if patient is None:
        return jsonify({"error": "could not verify patient"}), 404
    appointments = get_upcoming_appointments(patient["patient_id"], actor="voice_tool:get_upcoming_appointments")
    return jsonify({"appointments": appointments})


@app.route("/tools/check_availability", methods=["POST"])
@require_tools_secret
def tool_check_availability():
    provider_id = request.json["provider_id"]
    day = datetime.fromisoformat(request.json["day"])
    slots = get_open_slots(provider_id, day)
    return jsonify({"slots": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in slots]})


@app.route("/tools/find_new_appointment_slots", methods=["POST"])
@require_tools_secret
def tool_find_new_appointment_slots():
    """For booking a brand-new appointment (no existing one to anchor
    to) -- finds the soonest availability across any provider, starting
    tomorrow. Requires verification first, same as the other tools that
    touch patient-specific booking."""
    phone = request.json["phone"]
    dob = parse_dob(request.json["dob"])
    if dob is None:
        return jsonify({"error": "could not parse date of birth"}), 400
    patient = verify_patient(phone, dob, actor="voice_tool:find_new_appointment_slots")
    if patient is None:
        return jsonify({"error": "could not verify patient"}), 404
    provider, slots = find_soonest_slots_any_provider(datetime.now() + timedelta(days=1))
    if not slots:
        return jsonify({"slots": [], "provider": None})
    return jsonify({
        "provider": provider,
        "slots": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in slots],
    })


@app.route("/tools/book_new_appointment", methods=["POST"])
@require_tools_secret
def tool_book_new_appointment():
    body = request.json
    phone = body["phone"]
    dob = parse_dob(body["dob"])
    if dob is None:
        return jsonify({"error": "could not parse date of birth"}), 400
    patient = verify_patient(phone, dob, actor="voice_tool:book_new_appointment")
    if patient is None:
        return jsonify({"error": "could not verify patient"}), 404
    new_id = book_new_appointment(
        patient["patient_id"],
        patient["source_patient_id"],
        body["provider_id"],
        datetime.fromisoformat(body["new_start"]),
        datetime.fromisoformat(body["new_end"]),
        actor="voice_tool:book_new_appointment",
    )
    return jsonify({"status": "booked", "appointment_id": new_id})


@app.route("/tools/reschedule_appointment", methods=["POST"])
@require_tools_secret
def tool_reschedule_appointment():
    body = request.json
    phone = body["phone"]
    dob = parse_dob(body["dob"])
    if dob is None:
        return jsonify({"error": "could not parse date of birth"}), 400
    patient = verify_patient(phone, dob, actor="voice_tool:reschedule_appointment")
    if patient is None:
        return jsonify({"error": "could not verify patient"}), 404
    reschedule_appointment(
        body["appointment_id"],
        datetime.fromisoformat(body["new_start"]),
        datetime.fromisoformat(body["new_end"]),
        patient["source_patient_id"],
        actor="voice_tool:reschedule_appointment",
        patient_id=patient["patient_id"],
    )
    return jsonify({"status": "rescheduled"})


if __name__ == "__main__":
    # debug=True is deliberately not used here -- it enables the Werkzeug
    # debugger, which allows arbitrary code execution if this port is ever
    # reachable from outside localhost. Run behind a real WSGI server
    # (gunicorn) with TLS termination in front for anything beyond local testing.
    app.run(host="127.0.0.1", port=5000)
