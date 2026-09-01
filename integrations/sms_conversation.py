"""
The actual SMS conversation logic, independent of Telnyx or any specific
transport -- webhook_server.py is the thin adapter that calls this.

Design goals:
1. Handle the common cases (YES, RESCHEDULE, BOOK, picking an offered
   slot) with plain deterministic logic and zero LLM calls -- faster,
   free, and can't hallucinate a wrong appointment time. Only genuinely
   open-ended replies fall back to the LLM (llm_fallback.py), which
   gets its own tool access to the same booking functions.
2. Identity verification before any fresh disclosure or change: a plain
   "YES" just acknowledges an appointment we already texted to this
   number (no new PHI revealed, low risk) and needs no extra check. But
   RESCHEDULE and BOOK both disclose appointment details and lead to a
   write, so they require phone + date-of-birth verification first
   (book.verify_patient) -- phone number alone isn't sufficient per
   HIPAA best practice. Verification happens once per conversation and
   is cached in `state`, not re-asked on every message.
3. Never offer to connect the patient with a live person outside actual
   staffed hours (Mon-Fri 8am-5pm) -- every escalation message says
   *when* someone will follow up instead, using business_hours.

State is a plain dict per phone number: {"offered_slots": [...],
"verified_patient": {...}, "pending_verification_for": "reschedule"|"book",
"failed_verification_attempts": 0}. webhook_server.py is responsible
for persisting it (in-memory works for a demo; production should use a
small table, not memory that resets on restart).
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import openai

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "conversation"))

from book import (
    resolve_patient_by_phone, get_upcoming_appointments, reschedule_appointment,
    book_new_appointment, verify_patient, parse_dob, SchedulingError,
)
from availability import find_soonest_slots, find_soonest_slots_any_provider, AvailabilityError
from business_hours import next_staffed_description
import rollout_stage
import sms_templates as t

# Which LLM handles open-ended replies -- set LLM_PROVIDER=openai in .env
# to use an OpenAI key instead of an Anthropic one (e.g. while testing
# with existing OpenAI credit before an Anthropic account is set up).
# Both implement the identical handle_open_ended(phone, text, state)
# contract and share the same tool logic (llm_tools.py) -- swapping
# providers changes nothing else in this file.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
if LLM_PROVIDER == "openai":
    from llm_fallback_openai import handle_open_ended
else:
    from llm_fallback import handle_open_ended

MAX_VERIFICATION_ATTEMPTS = 2


def fmt(dt: datetime):
    return dt.strftime("%A, %b %d"), dt.strftime("%-I:%M %p")


def _offer_reschedule_slots(patient: dict, state: dict) -> tuple[str, dict]:
    """Searches forward from the existing appointment's day, not just
    that one exact day -- if the appointment happens to fall on what's
    now a closed day (or that day fills up), we still want to offer the
    next real availability, not report "fully booked" when there's
    plenty open two days later. Found via a real test failure: the
    seeded appointment's day landed on a Saturday, and the old
    single-day check reported "fully booked" instead of searching on."""
    appts = get_upcoming_appointments(patient["patient_id"], actor="sms_webhook")
    if not appts:
        return t.nothing_to_reschedule(), state
    target = appts[0]
    day = datetime.fromisoformat(target["start_time"])
    slots = find_soonest_slots(target["provider_id"], day, limit=3)
    if not slots:
        return t.fully_booked_that_day(target["provider_name"], next_staffed_description()), state

    labeled = [(str(i + 1), s, e) for i, (s, e) in enumerate(slots)]
    state["offered_slots"] = [
        {"label": lbl, "mode": "reschedule", "appointment_id": target["appointment_id"],
         "provider_id": target["provider_id"], "provider_name": target["provider_name"],
         "source_patient_id": patient["source_patient_id"], "patient_id": patient["patient_id"],
         "start": s.isoformat(), "end": e.isoformat()}
        for lbl, s, e in labeled
    ]
    options = [f"{lbl}) {s.strftime('%a %-I:%M%p')}" for lbl, s, e in labeled]
    return t.reschedule_slot_offer(target["provider_name"], options), state


def _offer_new_appointment_slots(patient: dict, state: dict) -> tuple[str, dict]:
    provider, slots = find_soonest_slots_any_provider(datetime.now() + timedelta(days=1))
    if not slots:
        return t.fully_booked_that_day("our office", next_staffed_description()), state

    labeled = [(str(i + 1), s, e) for i, (s, e) in enumerate(slots)]
    state["offered_slots"] = [
        {"label": lbl, "mode": "book", "provider_id": provider["provider_id"],
         "provider_name": provider["name"], "source_patient_id": patient["source_patient_id"],
         "patient_id": patient["patient_id"], "start": s.isoformat(), "end": e.isoformat()}
        for lbl, s, e in labeled
    ]
    options = [f"{lbl}) {s.strftime('%a %-I:%M%p')}" for lbl, s, e in labeled]
    return t.new_appointment_offer(provider["name"], options), state


def _handle_inbound_sms_unsafe(from_phone: str, text: str, state: dict) -> tuple[str, dict]:
    """The real logic -- separated from handle_inbound_sms so the outer
    function can wrap this in one try/except without indenting the
    entire body."""
    text_clean = text.strip().upper()

    # Mid-verification: this message should be a date of birth.
    if state.get("pending_verification_for"):
        dob = parse_dob(text.strip())
        if dob is None:
            return t.verification_unparseable(), state

        patient = verify_patient(from_phone, dob, actor="sms_webhook")
        if patient is None:
            state["failed_verification_attempts"] = state.get("failed_verification_attempts", 0) + 1
            if state["failed_verification_attempts"] >= MAX_VERIFICATION_ATTEMPTS:
                state.pop("pending_verification_for", None)
                return t.verification_escalate(next_staffed_description()), state
            return t.verification_retry(), state

        # Verified -- pick up whatever they originally asked for.
        intent = state.pop("pending_verification_for")
        state["verified_patient"] = patient
        state.pop("failed_verification_attempts", None)
        if intent == "reschedule":
            return _offer_reschedule_slots(patient, state)
        if intent == "book":
            return _offer_new_appointment_slots(patient, state)

    # Patient is confirming their existing appointment -- this just
    # acknowledges something we already texted to this number, no fresh
    # PHI disclosure, so no verification needed.
    if text_clean == "YES":
        patient = resolve_patient_by_phone(from_phone, actor="sms_webhook")
        if patient is None:
            return t.no_account_found(), state
        appts = get_upcoming_appointments(patient["patient_id"], actor="sms_webhook")
        if not appts:
            return t.nothing_to_confirm(), state
        date_str, time_str = fmt(datetime.fromisoformat(appts[0]["start_time"]))
        return t.confirmation_ack(date_str, time_str), state

    # Patient wants to reschedule -- re-discloses appointment details and
    # leads to a write, so verify identity first (once per conversation).
    # Checked before verification, not after: no point asking for a DOB
    # for a capability that's not even turned on yet at this rollout stage.
    if "RESCHEDULE" in text_clean:
        if not rollout_stage.is_enabled("reschedule"):
            return t.capability_not_yet_enabled(next_staffed_description()), state
        if state.get("verified_patient"):
            return _offer_reschedule_slots(state["verified_patient"], state)
        state["pending_verification_for"] = "reschedule"
        return t.verification_prompt(), state

    # Patient wants a brand-new appointment -- same verification policy.
    if "BOOK" in text_clean or "APPOINTMENT" in text_clean or "NEW" in text_clean:
        if not rollout_stage.is_enabled("booking"):
            return t.capability_not_yet_enabled(next_staffed_description()), state
        if state.get("verified_patient"):
            return _offer_new_appointment_slots(state["verified_patient"], state)
        state["pending_verification_for"] = "book"
        return t.verification_prompt(), state

    # Patient is picking one of the offered slots by number.
    if text_clean in {"1", "2", "3"} and state.get("offered_slots"):
        choice = next((o for o in state["offered_slots"] if o["label"] == text_clean), None)
        if choice:
            new_start = datetime.fromisoformat(choice["start"])
            new_end = datetime.fromisoformat(choice["end"])
            state.pop("offered_slots", None)
            if choice["mode"] == "reschedule":
                reschedule_appointment(
                    choice["appointment_id"], new_start, new_end, choice["source_patient_id"],
                    actor="sms_webhook", patient_id=choice["patient_id"],
                )
                date_str, time_str = fmt(new_start)
                return t.reschedule_confirmed(choice["provider_name"], date_str, time_str), state
            else:  # mode == "book"
                book_new_appointment(
                    choice["patient_id"], choice["source_patient_id"], choice["provider_id"],
                    new_start, new_end, actor="sms_webhook",
                )
                date_str, time_str = fmt(new_start)
                return t.new_appointment_confirmed(choice["provider_name"], date_str, time_str), state

    # Anything else -- genuinely open-ended, hand off to the LLM (with
    # tool access to the same booking functions, and the same warm
    # persona) rather than guessing with more keyword matching.
    return handle_open_ended(from_phone, text, state)


def handle_inbound_sms(from_phone: str, text: str, state: dict) -> tuple[str, dict]:
    """Returns (reply_text, updated_state). Never raises -- any database,
    availability, or LLM-API failure becomes a calm apology message
    instead of a crash, so a bad moment in PracticeWorks connectivity or
    a missing/invalid ANTHROPIC_API_KEY never turns into a broken
    conversation or a Telnyx retry storm."""
    state = dict(state)  # don't mutate caller's copy
    try:
        return _handle_inbound_sms_unsafe(from_phone, text, state)
    except (SchedulingError, AvailabilityError, anthropic.APIError, openai.APIError):
        return t.system_trouble(next_staffed_description()), state
