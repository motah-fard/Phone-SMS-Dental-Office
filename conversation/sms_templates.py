"""
SMS templates for Dental Arts Practice. Warm, short, a couple of tasteful
emoji -- not stacked on every line. These are f-string templates, not an
LLM call: fast, predictable, and free to send for the routine cases
(reminder, confirmation, reschedule). The AI/LLM layer only takes over
for open-ended replies (see conversation/voice_persona.md for the tone
that should carry over into free-form SMS replies too).
"""

PRACTICE_NAME = "Dental Arts Practice"
SIGNATURE_EMOJI = "🦷"


def appointment_reminder(first_name: str, provider_name: str, date_str: str, time_str: str) -> str:
    return (
        f"Hi {first_name}! {SIGNATURE_EMOJI} Friendly reminder from {PRACTICE_NAME} — "
        f"you're set with {provider_name} on {date_str} at {time_str} 📅. "
        f"Reply YES to confirm, or RESCHEDULE if you need a new time. See you soon! 😊"
    )


def confirmation_ack(date_str: str, time_str: str) -> str:
    return f"Awesome, you're confirmed for {date_str} at {time_str} ✅ We'll see you then!"


def reschedule_slot_offer(provider_name: str, slot_options: list[str]) -> str:
    options = ", ".join(slot_options)
    return (
        f"No problem! Here's what's open with {provider_name}: {options} 🕒 "
        f"Just reply with the one that works best."
    )


def reschedule_confirmed(provider_name: str, date_str: str, time_str: str) -> str:
    return (
        f"You're all set — {date_str} at {time_str} with {provider_name} "
        f"{SIGNATURE_EMOJI}📅 Thanks for letting us know!"
    )


def missed_call_followup(first_name: str) -> str:
    return (
        f"Hi {first_name}, sorry we missed your call! 📞 Want to book or reschedule an "
        f"appointment? Just reply here and I'll take care of it."
    )


def ai_disclosure_footer() -> str:
    """Appended to the first message in any new SMS thread -- same
    disclosure requirement as the voice opening, worded for text."""
    return "(This is Moty, the practice's AI assistant — happy to help anytime!)"
