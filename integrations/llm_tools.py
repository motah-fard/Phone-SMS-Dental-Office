"""
Provider-agnostic tool definitions and execution logic, shared by
llm_fallback.py (Anthropic) and llm_fallback_openai.py (OpenAI). The
actual conversation loop and message-format wrangling differ enough
between the two SDKs that they stay in separate files -- but the tools
themselves (what they do, how they touch book.py) should exist exactly
once, not duplicated per provider.

TOOL_DEFINITIONS is provider-neutral (name/description/parameters as
plain JSON Schema); each provider file wraps these into whatever shape
its SDK expects (Anthropic's `input_schema` vs OpenAI's `parameters`
inside a `function` wrapper).
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "conversation"))

from book import (
    verify_patient, get_upcoming_appointments, reschedule_appointment,
    book_new_appointment, parse_dob, SchedulingError,
)
from availability import get_open_slots, find_soonest_slots_any_provider, AvailabilityError
from business_hours import is_staffed, next_staffed_description
import rollout_stage

TOOL_DEFINITIONS = [
    {
        "name": "verify_patient",
        "description": "Verify the texter's identity with their date of birth before disclosing or changing any appointment. Must succeed before any tool below will work.",
        "parameters": {
            "type": "object",
            "properties": {"dob": {"type": "string", "description": "Date of birth as the patient stated it, e.g. MM/DD/YYYY"}},
            "required": ["dob"],
        },
    },
    {
        "name": "get_upcoming_appointments",
        "description": "List the verified patient's upcoming appointments.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "check_availability",
        "description": "Get open slots for one specific provider on a specific day -- use when rescheduling an existing appointment (the provider is already known).",
        "parameters": {
            "type": "object",
            "properties": {
                "provider_id": {"type": "integer"},
                "day": {"type": "string", "description": "ISO date, e.g. 2026-09-02"},
            },
            "required": ["provider_id", "day"],
        },
    },
    {
        "name": "reschedule_appointment",
        "description": "Move an existing appointment to a new confirmed time.",
        "parameters": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer"},
                "new_start": {"type": "string", "description": "ISO datetime"},
                "new_end": {"type": "string", "description": "ISO datetime"},
            },
            "required": ["appointment_id", "new_start", "new_end"],
        },
    },
    {
        "name": "find_new_appointment_slots",
        "description": "Find the soonest available slot across any provider, for a patient who doesn't have an appointment yet or wants an additional one.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "book_new_appointment",
        "description": "Book a brand-new appointment at a specific time slot returned by find_new_appointment_slots.",
        "parameters": {
            "type": "object",
            "properties": {
                "provider_id": {"type": "integer"},
                "new_start": {"type": "string", "description": "ISO datetime"},
                "new_end": {"type": "string", "description": "ISO datetime"},
            },
            "required": ["provider_id", "new_start", "new_end"],
        },
    },
    {
        "name": "check_staffed_hours",
        "description": "Check whether front-desk staff are available right now -- call this before ever suggesting someone will call the patient back immediately.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def execute_tool(name: str, tool_input: dict, phone: str, session: dict) -> dict:
    """`session` holds cross-turn context for THIS conversation (the
    verified patient, once verify_patient succeeds) -- `phone` always
    comes from the caller (never from tool_input), so the model can't
    supply or override it, regardless of which provider is calling this."""
    try:
        if name == "verify_patient":
            dob = parse_dob(tool_input["dob"])
            if dob is None:
                return {"verified": False, "error": "could not parse date of birth"}
            patient = verify_patient(phone, dob, actor="sms_llm_fallback")
            if patient is None:
                return {"verified": False}
            session["verified_patient"] = patient
            return {"verified": True, "first_name": patient["first_name"]}

        patient = session.get("verified_patient")

        if name == "get_upcoming_appointments":
            if not patient:
                return {"error": "not verified yet -- call verify_patient first"}
            return {"appointments": get_upcoming_appointments(patient["patient_id"], actor="sms_llm_fallback")}

        if name == "check_availability":
            day = datetime.fromisoformat(tool_input["day"])
            slots = get_open_slots(tool_input["provider_id"], day)
            return {"slots": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in slots]}

        if name == "reschedule_appointment":
            if not rollout_stage.is_enabled("reschedule"):
                return {"error": "rescheduling isn't available yet -- tell the patient our front-desk team will follow up directly"}
            if not patient:
                return {"error": "not verified yet -- call verify_patient first"}
            reschedule_appointment(
                tool_input["appointment_id"],
                datetime.fromisoformat(tool_input["new_start"]),
                datetime.fromisoformat(tool_input["new_end"]),
                patient["source_patient_id"],
                actor="sms_llm_fallback", patient_id=patient["patient_id"],
            )
            return {"status": "rescheduled"}

        if name == "find_new_appointment_slots":
            if not rollout_stage.is_enabled("booking"):
                return {"error": "booking new appointments isn't available yet -- tell the patient our front-desk team will follow up directly"}
            if not patient:
                return {"error": "not verified yet -- call verify_patient first"}
            provider, slots = find_soonest_slots_any_provider(datetime.now() + timedelta(days=1))
            if not slots:
                return {"slots": [], "provider": None}
            return {"provider": provider, "slots": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in slots]}

        if name == "book_new_appointment":
            if not rollout_stage.is_enabled("booking"):
                return {"error": "booking new appointments isn't available yet -- tell the patient our front-desk team will follow up directly"}
            if not patient:
                return {"error": "not verified yet -- call verify_patient first"}
            new_id = book_new_appointment(
                patient["patient_id"], patient["source_patient_id"], tool_input["provider_id"],
                datetime.fromisoformat(tool_input["new_start"]), datetime.fromisoformat(tool_input["new_end"]),
                actor="sms_llm_fallback",
            )
            return {"status": "booked", "appointment_id": new_id}

        if name == "check_staffed_hours":
            return {"staffed": is_staffed(), "next_available": next_staffed_description()}

        return {"error": f"unknown tool {name}"}
    except (SchedulingError, AvailabilityError):
        return {"error": "a backend system error occurred -- apologize and suggest calling the office directly"}


def system_prompt(sms_adaptation: str) -> str:
    persona_path = Path(__file__).parent.parent / "conversation" / "voice_persona.md"
    return persona_path.read_text() + sms_adaptation


SMS_ADAPTATION = (
    "\n\nYou are responding over SMS text, not a live phone call -- keep replies to "
    "1-3 short sentences, and skip the phone-call opening line above since this is a "
    "reply within an existing text thread, not the start of a call."
)
