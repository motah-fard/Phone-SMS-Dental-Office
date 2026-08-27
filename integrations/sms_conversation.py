"""
The actual SMS conversation logic, independent of Telnyx or any specific
transport -- webhook_server.py is the thin adapter that calls this.

Design goals:
1. Handle the common cases (YES, RESCHEDULE, picking an offered slot)
   with plain deterministic logic and zero LLM calls -- faster, free,
   and can't hallucinate a wrong appointment time. Only genuinely
   open-ended replies fall back to the LLM (llm_fallback.py, not built
   yet -- stubbed here).
2. Identity verification before any fresh disclosure or change: a plain
   "YES" just acknowledges an appointment we already texted to this
   number (no new PHI revealed, low risk) and needs no extra check. But
   RESCHEDULE re-discloses appointment details and leads to a write, so
   it requires phone + date-of-birth verification first (book.verify_patient) --
   phone number alone isn't sufficient per HIPAA best practice (a lost
   phone or a family member could otherwise probe or change someone's
   appointment). Verification happens once per conversation and is
   cached in `state`, not re-asked on every message.

State is a plain dict per phone number: {"offered_slots": [...],
"verified_patient": {...}, "pending_verification_for": "reschedule",
"failed_verification_attempts": 0}. webhook_server.py is responsible
for persisting it (in-memory works for a demo; production should use a
small table, not memory that resets on restart).
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "conversation"))

from book import resolve_patient_by_phone, get_upcoming_appointments, reschedule_appointment, verify_patient, parse_dob
from availability import get_open_slots
import sms_templates as t

MAX_VERIFICATION_ATTEMPTS = 2


def fmt(dt: datetime):
    return dt.strftime("%A, %b %d"), dt.strftime("%-I:%M %p")


def _offer_reschedule_slots(patient: dict, state: dict) -> tuple[str, dict]:
    appts = get_upcoming_appointments(patient["patient_id"], actor="sms_webhook")
    if not appts:
        return "I don't see an upcoming appointment to reschedule -- want to book a new one instead?", state
    target = appts[0]
    day = datetime.fromisoformat(target["start_time"])
    slots = get_open_slots(target["provider_id"], day)[:3]
    if not slots:
        return f"Hmm, {target['provider_name']} is fully booked that day -- I'll have the front desk call you to find another time.", state

    labeled = [(str(i + 1), s, e) for i, (s, e) in enumerate(slots)]
    state["offered_slots"] = [
        {"label": lbl, "appointment_id": target["appointment_id"],
         "provider_id": target["provider_id"], "provider_name": target["provider_name"],
         "source_patient_id": patient["source_patient_id"], "patient_id": patient["patient_id"],
         "start": s.isoformat(), "end": e.isoformat()}
        for lbl, s, e in labeled
    ]
    options = [f"{lbl}) {s.strftime('%a %-I:%M%p')}" for lbl, s, e in labeled]
    return t.reschedule_slot_offer(target["provider_name"], options), state


def handle_inbound_sms(from_phone: str, text: str, state: dict) -> tuple[str, dict]:
    """Returns (reply_text, updated_state)."""
    text_clean = text.strip().upper()
    state = dict(state)  # don't mutate caller's copy

    # Mid-verification: this message should be a date of birth.
    if state.get("pending_verification_for"):
        dob = parse_dob(text.strip())
        if dob is None:
            return "Sorry, I didn't quite catch that -- could you send your date of birth as MM/DD/YYYY?", state

        patient = verify_patient(from_phone, dob, actor="sms_webhook")
        if patient is None:
            state["failed_verification_attempts"] = state.get("failed_verification_attempts", 0) + 1
            if state["failed_verification_attempts"] >= MAX_VERIFICATION_ATTEMPTS:
                state.pop("pending_verification_for", None)
                return "I wasn't able to verify that -- I'll have our front desk team give you a call to help directly.", state
            return "Hmm, that doesn't match what's on file -- mind double-checking your date of birth?", state

        # Verified -- pick up whatever they originally asked for.
        intent = state.pop("pending_verification_for")
        state["verified_patient"] = patient
        state.pop("failed_verification_attempts", None)
        if intent == "reschedule":
            return _offer_reschedule_slots(patient, state)

    # Patient is confirming their existing appointment -- this just
    # acknowledges something we already texted to this number, no fresh
    # PHI disclosure, so no verification needed.
    if text_clean == "YES":
        patient = resolve_patient_by_phone(from_phone, actor="sms_webhook")
        if patient is None:
            return (
                "Hi! I couldn't find an account with this number -- please call "
                "the office directly and we'll get you sorted. 🦷",
                state,
            )
        appts = get_upcoming_appointments(patient["patient_id"], actor="sms_webhook")
        if not appts:
            return "Looks like there's nothing on the books to confirm right now!", state
        date_str, time_str = fmt(datetime.fromisoformat(appts[0]["start_time"]))
        return t.confirmation_ack(date_str, time_str), state

    # Patient wants to reschedule -- this re-discloses appointment details
    # and leads to a write, so verify identity first (once per conversation).
    if "RESCHEDULE" in text_clean:
        if state.get("verified_patient"):
            return _offer_reschedule_slots(state["verified_patient"], state)
        state["pending_verification_for"] = "reschedule"
        return "Of course! Just to pull up the right chart, can you confirm your date of birth? (MM/DD/YYYY)", state

    # Patient is picking one of the offered slots by number.
    if text_clean in {"1", "2", "3"} and state.get("offered_slots"):
        choice = next((o for o in state["offered_slots"] if o["label"] == text_clean), None)
        if choice:
            new_start = datetime.fromisoformat(choice["start"])
            new_end = datetime.fromisoformat(choice["end"])
            reschedule_appointment(
                choice["appointment_id"], new_start, new_end, choice["source_patient_id"],
                actor="sms_webhook", patient_id=choice["patient_id"],
            )
            date_str, time_str = fmt(new_start)
            state.pop("offered_slots", None)
            return t.reschedule_confirmed(choice["provider_name"], date_str, time_str), state

    # Anything else -- open-ended, needs the LLM. Not wired up yet.
    return (
        "[LLM fallback not wired up yet -- would hand this off to Moty with "
        "the persona prompt + tool access to book.py functions]",
        state,
    )
