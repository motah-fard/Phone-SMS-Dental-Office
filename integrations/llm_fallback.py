"""
LLM fallback for SMS replies that don't match a known deterministic
pattern (YES/RESCHEDULE/BOOK/slot-pick) -- see sms_conversation.py's
_handle_inbound_sms_unsafe, which calls handle_open_ended() below as
its last resort. Uses the same warm persona as the voice assistant,
with tool access to the real scheduling functions so it can act, not
just chat.

Requires ANTHROPIC_API_KEY in the environment. Testing against fake
data (source_system's simulated PracticeWorks, or the real PracticeWorks
TUTOR training database) does NOT require the Anthropic BAA -- no real
PHI is involved either way. The BAA is required before this ever
touches real PracticeWorks (PWORKS) data.

Security: `phone` is bound from the outer call (webhook_server.py's
verified Telnyx payload), never taken from the model's tool-call input
-- same principle as the voice tools. The model can ask the patient for
their date of birth and pass THAT to verify_patient, but it can never
supply a phone number itself.

Known limitation: `history` stores raw SDK message dicts (including
tool_use/tool_result blocks), which aren't cleanly JSON-serializable.
Fine for in-memory state today; whoever builds the real persistent
conversation-state store (see pre_launch_checklist.md) will need to
serialize this properly, not just json.dumps() it as-is.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "conversation"))

from book import (
    verify_patient, get_upcoming_appointments, reschedule_appointment,
    book_new_appointment, parse_dob, SchedulingError,
)
from availability import get_open_slots, find_soonest_slots_any_provider, AvailabilityError
from business_hours import is_staffed, next_staffed_description

MODEL = "claude-sonnet-5"
MAX_TOOL_ITERATIONS = 5  # hard cap -- never loop forever on a confused tool cycle
MAX_HISTORY_MESSAGES = 20  # caps prompt growth on a long-running thread

_PERSONA_PATH = Path(__file__).parent.parent / "conversation" / "voice_persona.md"
_SMS_ADAPTATION = (
    "\n\nYou are responding over SMS text, not a live phone call -- keep replies to "
    "1-3 short sentences, and skip the phone-call opening line above since this is a "
    "reply within an existing text thread, not the start of a call."
)

TOOLS = [
    {
        "name": "verify_patient",
        "description": "Verify the texter's identity with their date of birth before disclosing or changing any appointment. Must succeed before any tool below will work.",
        "input_schema": {
            "type": "object",
            "properties": {"dob": {"type": "string", "description": "Date of birth as the patient stated it, e.g. MM/DD/YYYY"}},
            "required": ["dob"],
        },
    },
    {
        "name": "get_upcoming_appointments",
        "description": "List the verified patient's upcoming appointments.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_availability",
        "description": "Get open slots for one specific provider on a specific day -- use when rescheduling an existing appointment (the provider is already known).",
        "input_schema": {
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
        "input_schema": {
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
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "book_new_appointment",
        "description": "Book a brand-new appointment at a specific time slot returned by find_new_appointment_slots.",
        "input_schema": {
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
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _system_prompt() -> str:
    return _PERSONA_PATH.read_text() + _SMS_ADAPTATION


def _execute_tool(name: str, tool_input: dict, phone: str, session: dict) -> dict:
    """`session` holds cross-turn context for THIS conversation (the
    verified patient, once verify_patient succeeds) -- `phone` always
    comes from the caller of handle_open_ended, never from tool_input,
    so the model can't supply or override it."""
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
            if not patient:
                return {"error": "not verified yet -- call verify_patient first"}
            provider, slots = find_soonest_slots_any_provider(datetime.now() + timedelta(days=1))
            if not slots:
                return {"slots": [], "provider": None}
            return {"provider": provider, "slots": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in slots]}

        if name == "book_new_appointment":
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


def handle_open_ended(phone: str, text: str, state: dict, client: "anthropic.Anthropic | None" = None) -> tuple[str, dict]:
    """Entry point sms_conversation.py calls for anything that doesn't
    match a deterministic pattern. `client` is injectable so tests can
    pass a fake one without a real API key -- see tests/test_llm_fallback.py."""
    client = client or anthropic.Anthropic()
    state = dict(state)
    session = state.setdefault("llm_session", {})
    history = state.setdefault("llm_history", [])

    history.append({"role": "user", "content": text})
    history[:] = history[-MAX_HISTORY_MESSAGES:]

    messages = list(history)
    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL, max_tokens=500, system=_system_prompt(),
            tools=TOOLS, messages=messages,
        )
        if response.stop_reason != "tool_use":
            final_text = "".join(block.text for block in response.content if block.type == "text")
            history.append({"role": "assistant", "content": final_text})
            return final_text, state

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _execute_tool(block.name, block.input, phone, session)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(result)})
        messages.append({"role": "user", "content": tool_results})

    # Hit MAX_TOOL_ITERATIONS without a final answer -- don't loop forever.
    fallback = "Let me have our front-desk team follow up on that directly."
    history.append({"role": "assistant", "content": fallback})
    return fallback, state
