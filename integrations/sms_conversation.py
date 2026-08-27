"""
The actual SMS conversation logic, independent of Telnyx or any specific
transport -- webhook_server.py is the thin adapter that calls this.

Design goal: handle the common cases (YES, RESCHEDULE, picking an
offered slot) with plain deterministic logic and zero LLM calls -- it's
faster, free, and can't hallucinate a wrong appointment time. Only
genuinely open-ended replies fall back to the LLM (llm_fallback.py,
not built yet -- stubbed here).

State is a plain dict per phone number: {"offered_slots": [...],
"appointment_id": ..., "provider_id": ...}. webhook_server.py is
responsible for persisting it (in-memory works for a demo; production
should use a small table, not memory that resets on restart).
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "conversation"))

from book import resolve_patient_by_phone, get_upcoming_appointments, reschedule_appointment
from availability import get_open_slots
import sms_templates as t


def fmt(dt: datetime):
    return dt.strftime("%A, %b %d"), dt.strftime("%-I:%M %p")


def handle_inbound_sms(from_phone: str, text: str, state: dict) -> tuple[str, dict]:
    """Returns (reply_text, updated_state)."""
    text_clean = text.strip().upper()
    state = dict(state)  # don't mutate caller's copy

    patient = resolve_patient_by_phone(from_phone)
    if patient is None:
        return (
            "Hi! I couldn't find an account with this number -- please call "
            "the office directly and we'll get you sorted. 🦷",
            state,
        )

    # Patient is confirming their existing appointment.
    if text_clean == "YES":
        appts = get_upcoming_appointments(patient["patient_id"])
        if not appts:
            return "Looks like there's nothing on the books to confirm right now!", state
        date_str, time_str = fmt(datetime.fromisoformat(appts[0]["start_time"]))
        return t.confirmation_ack(date_str, time_str), state

    # Patient wants to reschedule -- offer real open slots, remember them.
    if "RESCHEDULE" in text_clean:
        appts = get_upcoming_appointments(patient["patient_id"])
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
             "source_patient_id": patient["source_patient_id"],
             "start": s.isoformat(), "end": e.isoformat()}
            for lbl, s, e in labeled
        ]
        options = [f"{lbl}) {s.strftime('%a %-I:%M%p')}" for lbl, s, e in labeled]
        return t.reschedule_slot_offer(target["provider_name"], options), state

    # Patient is picking one of the offered slots by number.
    if text_clean in {"1", "2", "3"} and state.get("offered_slots"):
        choice = next((o for o in state["offered_slots"] if o["label"] == text_clean), None)
        if choice:
            new_start = datetime.fromisoformat(choice["start"])
            new_end = datetime.fromisoformat(choice["end"])
            reschedule_appointment(
                choice["appointment_id"], new_start, new_end, choice["source_patient_id"]
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
