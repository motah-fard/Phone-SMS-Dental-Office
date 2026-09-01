"""
SMS templates for Dental Arts Practice. Warm, calm, short, a couple of
tasteful emoji -- not stacked on every line. These are f-string
templates, not an LLM call: fast, predictable, and free to send for the
routine cases (reminder, confirmation, reschedule, booking). The
AI/LLM layer only takes over for open-ended replies.

Every patient-facing string lives here, not inline in sms_conversation.py
-- one place to review or adjust wording/tone without hunting through
conversation logic.
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


def new_appointment_offer(provider_name: str, slot_options: list[str]) -> str:
    options = ", ".join(slot_options)
    return (
        f"Happy to get you booked! Here's the soonest we've got with {provider_name}: "
        f"{options} 🕒 Reply with the one that works, or let us know if you'd like a "
        f"different provider."
    )


def new_appointment_confirmed(provider_name: str, date_str: str, time_str: str) -> str:
    return (
        f"You're all booked — {date_str} at {time_str} with {provider_name} "
        f"{SIGNATURE_EMOJI}📅 We're looking forward to seeing you!"
    )


def missed_call_followup(first_name: str) -> str:
    return (
        f"Hi {first_name}, sorry we missed your call! 📞 Want to book or reschedule an "
        f"appointment? Just reply here and I'll take care of it."
    )


def verification_prompt() -> str:
    return "Of course! Just to pull up the right chart, can you confirm your date of birth? (MM/DD/YYYY)"


def verification_retry() -> str:
    return "Hmm, that doesn't match what's on file — mind double-checking your date of birth?"


def verification_unparseable() -> str:
    return "Sorry, I didn't quite catch that — could you send your date of birth as MM/DD/YYYY?"


def verification_escalate(next_available: str) -> str:
    return (
        f"I wasn't able to verify that, so I don't want to guess with your appointment — "
        f"our front desk team will give you a call {next_available} to help directly. Sorry "
        f"for the extra step!"
    )


def no_account_found() -> str:
    return (
        f"Hi! I couldn't find an account with this number — please call the office "
        f"directly and we'll get you sorted. {SIGNATURE_EMOJI}"
    )


def nothing_to_confirm() -> str:
    return "Looks like there's nothing on the books to confirm right now!"


def nothing_to_reschedule() -> str:
    return "I don't see an upcoming appointment to reschedule — want to book a new one instead?"


def fully_booked_that_day(provider_name: str, next_available: str) -> str:
    return (
        f"Hmm, {provider_name} is fully booked that day — I'll have the front desk "
        f"take a look {next_available} to find you another time."
    )


def capability_not_yet_enabled(next_available: str) -> str:
    """Shown when ROLLOUT_STAGE hasn't turned this capability on yet --
    never mention rollout stages or internal system state to a patient,
    just route them to a human warmly, same as any other escalation."""
    return (
        f"I'm not able to take care of that myself just yet — I'll have our front "
        f"desk team reach out {next_available} to help you directly."
    )


def system_trouble(next_available: str) -> str:
    """Shown when a database/system error happens mid-conversation --
    never expose the raw error to a patient, just a calm apology and a
    path forward."""
    return (
        f"I'm having trouble reaching our scheduling system right now — sorry about "
        f"that! Please call the office directly, or our team will follow up {next_available}."
    )


def ai_disclosure_footer() -> str:
    """Appended to the first message in any new SMS thread -- same
    disclosure requirement as the voice opening, worded for text."""
    return "(This is Moty, the practice's AI assistant — happy to help anytime!)"
