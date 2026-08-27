"""
integrations/webhook_server.py -- Flask app tested via its test client.

The signature-verification test uses a REAL Ed25519 keypair (via
PyNaCl), not a mocked check -- this is the one security control between
the internet and this server, so it's worth proving the actual crypto
path works, not just that some function returns True/False.
"""
import base64
import json
import time

import pytest
from nacl.signing import SigningKey

import webhook_server as ws


@pytest.fixture
def client():
    ws.app.config["TESTING"] = True
    return ws.app.test_client()


@pytest.fixture
def signing_keypair(monkeypatch):
    signing_key = SigningKey.generate()
    public_b64 = base64.b64encode(bytes(signing_key.verify_key)).decode()
    monkeypatch.setattr(ws, "TELNYX_PUBLIC_KEY", public_b64)
    return signing_key


def sign(signing_key, timestamp: str, raw_body: bytes) -> str:
    signed_payload = f"{timestamp}|".encode() + raw_body
    signature = signing_key.sign(signed_payload).signature
    return base64.b64encode(signature).decode()


# --- SMS webhook signature verification (real crypto) ---

def test_sms_webhook_rejects_missing_signature(client):
    resp = client.post("/webhooks/telnyx/sms", json={"data": {"payload": {}}})
    assert resp.status_code == 401


def test_sms_webhook_accepts_validly_signed_request(client, signing_keypair, fresh_db, monkeypatch):
    sent = {}
    monkeypatch.setattr(ws, "send_sms", lambda phone, text: sent.setdefault("args", (phone, text)))

    body = {"data": {"payload": {"from": {"phone_number": "+15551230001"}, "text": "YES"}}}
    raw_body = json.dumps(body).encode()
    timestamp = str(int(time.time()))
    signature = sign(signing_keypair, timestamp, raw_body)

    resp = client.post(
        "/webhooks/telnyx/sms", data=raw_body, content_type="application/json",
        headers={"telnyx-signature-ed25519": signature, "telnyx-timestamp": timestamp},
    )
    assert resp.status_code == 200
    assert "args" in sent
    assert sent["args"][0] == "+15551230001"
    assert "confirmed" in sent["args"][1].lower()


def test_sms_webhook_rejects_tampered_body_even_with_valid_signature(client, signing_keypair, fresh_db):
    original_body = json.dumps({"data": {"payload": {"from": {"phone_number": "+15551230001"}, "text": "YES"}}}).encode()
    timestamp = str(int(time.time()))
    signature = sign(signing_keypair, timestamp, original_body)

    tampered_body = json.dumps({"data": {"payload": {"from": {"phone_number": "+19995550000"}, "text": "YES"}}}).encode()

    resp = client.post(
        "/webhooks/telnyx/sms", data=tampered_body, content_type="application/json",
        headers={"telnyx-signature-ed25519": signature, "telnyx-timestamp": timestamp},
    )
    assert resp.status_code == 401


def test_sms_webhook_rejects_replayed_old_timestamp(client, signing_keypair, fresh_db):
    body = json.dumps({"data": {"payload": {"from": {"phone_number": "+15551230001"}, "text": "YES"}}}).encode()
    old_timestamp = str(int(time.time()) - 10_000)  # long past WEBHOOK_MAX_AGE_SECONDS
    signature = sign(signing_keypair, old_timestamp, body)

    resp = client.post(
        "/webhooks/telnyx/sms", data=body, content_type="application/json",
        headers={"telnyx-signature-ed25519": signature, "telnyx-timestamp": old_timestamp},
    )
    assert resp.status_code == 401


def test_sms_webhook_rejects_signature_from_a_different_key(client, fresh_db, monkeypatch):
    real_key = SigningKey.generate()
    attacker_key = SigningKey.generate()
    monkeypatch.setattr(ws, "TELNYX_PUBLIC_KEY", base64.b64encode(bytes(real_key.verify_key)).decode())

    body = json.dumps({"data": {"payload": {"from": {"phone_number": "+15551230001"}, "text": "YES"}}}).encode()
    timestamp = str(int(time.time()))
    forged_signature = sign(attacker_key, timestamp, body)  # signed with the WRONG key

    resp = client.post(
        "/webhooks/telnyx/sms", data=body, content_type="application/json",
        headers={"telnyx-signature-ed25519": forged_signature, "telnyx-timestamp": timestamp},
    )
    assert resp.status_code == 401


def test_sms_webhook_send_failure_does_not_500(client, signing_keypair, fresh_db, monkeypatch):
    """A TelnyxError sending the reply must not surface as a raw 500 --
    the conversation logic already succeeded, only delivery failed."""
    def boom(phone, text):
        raise ws.TelnyxError("simulated send failure")

    monkeypatch.setattr(ws, "send_sms", boom)
    body = json.dumps({"data": {"payload": {"from": {"phone_number": "+15551230001"}, "text": "YES"}}}).encode()
    timestamp = str(int(time.time()))
    signature = sign(signing_keypair, timestamp, body)

    resp = client.post(
        "/webhooks/telnyx/sms", data=body, content_type="application/json",
        headers={"telnyx-signature-ed25519": signature, "telnyx-timestamp": timestamp},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "reply_send_failed"


# --- /tools/* shared-secret auth ---

def test_tool_endpoint_rejects_missing_secret(client, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "correct-secret")
    resp = client.post("/tools/check_staffed_hours", json={})
    assert resp.status_code == 401


def test_tool_endpoint_rejects_wrong_secret(client, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "correct-secret")
    resp = client.post("/tools/check_staffed_hours", json={}, headers={"X-Internal-Tool-Secret": "wrong"})
    assert resp.status_code == 401


def test_tool_endpoint_accepts_correct_secret(client, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "correct-secret")
    resp = client.post("/tools/check_staffed_hours", json={}, headers={"X-Internal-Tool-Secret": "correct-secret"})
    assert resp.status_code == 200
    assert "staffed" in resp.get_json()


def test_tool_endpoint_misconfigured_server_returns_500(client, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", None)
    resp = client.post("/tools/check_staffed_hours", json={}, headers={"X-Internal-Tool-Secret": "anything"})
    assert resp.status_code == 500


# --- /tools/* business logic ---

def test_verify_patient_tool_endpoint(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/verify_patient", json={"phone": "+15551230001", "dob": "04/12/1988"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["verified"] is True


def test_verify_patient_tool_endpoint_bad_dob_format(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/verify_patient", json={"phone": "+15551230001", "dob": "not a date"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 400


def test_verify_patient_tool_endpoint_wrong_dob(client, fresh_db, monkeypatch):
    """Valid FORMAT but wrong actual date of birth -- distinct from the
    bad-format test above, hits the 404 branch not the 400 one."""
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/verify_patient", json={"phone": "+15551230001", "dob": "01/01/1999"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 404
    assert resp.get_json()["verified"] is False


def test_get_upcoming_appointments_tool_endpoint(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/get_upcoming_appointments", json={"phone": "+15551230001", "dob": "04/12/1988"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 200
    assert len(resp.get_json()["appointments"]) == 1


def test_get_upcoming_appointments_tool_endpoint_bad_dob_format(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/get_upcoming_appointments", json={"phone": "+15551230001", "dob": "not a date"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 400


def test_get_upcoming_appointments_tool_endpoint_wrong_dob(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/get_upcoming_appointments", json={"phone": "+15551230001", "dob": "01/01/1999"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 404


def test_check_availability_tool_endpoint(client, fresh_db, monkeypatch):
    from datetime import datetime, timedelta
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    day = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    resp = client.post(
        "/tools/check_availability", json={"provider_id": 1, "day": day.isoformat()},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 200
    assert "slots" in resp.get_json()


def test_reschedule_appointment_tool_endpoint(client, fresh_db, monkeypatch):
    from datetime import datetime, timedelta
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    new_start = datetime.now() + timedelta(days=3)
    new_end = new_start + timedelta(minutes=30)
    resp = client.post(
        "/tools/reschedule_appointment",
        json={
            "phone": "+15551230001", "dob": "04/12/1988", "appointment_id": 1,
            "new_start": new_start.isoformat(), "new_end": new_end.isoformat(),
        },
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "rescheduled"


def test_book_new_appointment_tool_endpoint(client, fresh_db, monkeypatch):
    from datetime import datetime, timedelta
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    start = datetime.now() + timedelta(days=5)
    end = start + timedelta(minutes=30)
    resp = client.post(
        "/tools/book_new_appointment",
        json={
            "phone": "+15551230003", "dob": "07/23/1992", "provider_id": 1,
            "new_start": start.isoformat(), "new_end": end.isoformat(),
        },
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "booked"


def test_find_new_appointment_slots_tool_endpoint(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/find_new_appointment_slots", json={"phone": "+15551230003", "dob": "07/23/1992"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 200
    assert len(resp.get_json()["slots"]) > 0


def test_find_new_appointment_slots_tool_endpoint_bad_dob(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/find_new_appointment_slots", json={"phone": "+15551230003", "dob": "garbage"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 400


def test_find_new_appointment_slots_tool_endpoint_unverified(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/find_new_appointment_slots", json={"phone": "+15551230003", "dob": "01/01/1900"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 404


def test_find_new_appointment_slots_tool_endpoint_none_available(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    monkeypatch.setattr(ws, "find_soonest_slots_any_provider", lambda *a, **k: (None, []))
    resp = client.post(
        "/tools/find_new_appointment_slots", json={"phone": "+15551230003", "dob": "07/23/1992"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"slots": [], "provider": None}


def test_book_new_appointment_tool_endpoint_bad_dob(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/book_new_appointment",
        json={"phone": "+15551230003", "dob": "garbage", "provider_id": 1,
              "new_start": "2026-09-01T09:00:00", "new_end": "2026-09-01T09:30:00"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 400


def test_book_new_appointment_tool_endpoint_unverified(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/book_new_appointment",
        json={"phone": "+15551230003", "dob": "01/01/1900", "provider_id": 1,
              "new_start": "2026-09-01T09:00:00", "new_end": "2026-09-01T09:30:00"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 404


def test_reschedule_appointment_tool_endpoint_bad_dob(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/reschedule_appointment",
        json={"phone": "+15551230001", "dob": "garbage", "appointment_id": 1,
              "new_start": "2026-09-01T09:00:00", "new_end": "2026-09-01T09:30:00"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 400


def test_reschedule_appointment_tool_endpoint_unverified(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/reschedule_appointment",
        json={"phone": "+15551230001", "dob": "01/01/1900", "appointment_id": 1,
              "new_start": "2026-09-01T09:00:00", "new_end": "2026-09-01T09:30:00"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 404


# --- Malformed-request error handler ---

def test_malformed_request_missing_field_returns_400(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")
    resp = client.post(
        "/tools/get_upcoming_appointments", json={"phone": "+15551230001"},  # missing "dob"
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 400


# --- Backend-failure error handler ---

def test_scheduling_error_returns_503_not_leaking_details(client, fresh_db, monkeypatch):
    monkeypatch.setattr(ws, "TOOLS_SHARED_SECRET", "s3cret")

    def boom(*args, **kwargs):
        raise ws.SchedulingError("simulated db outage detail")

    monkeypatch.setattr(ws, "verify_patient", boom)
    resp = client.post(
        "/tools/get_upcoming_appointments", json={"phone": "+15551230001", "dob": "04/12/1988"},
        headers={"X-Internal-Tool-Secret": "s3cret"},
    )
    assert resp.status_code == 503
    assert "simulated db outage detail" not in resp.get_data(as_text=True)
