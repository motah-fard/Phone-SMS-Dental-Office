# Configuring the Telnyx AI Voice Assistant

This is dashboard/API configuration on Telnyx's side once the account +
BAA exist -- not something that lives in this repo as code, but this
doc is the reference for setting it up correctly.

## System prompt

Paste the contents of `conversation/voice_persona.md` in as the
assistant's system prompt/instructions field.

## Tools (function calling)

Register these three tools, pointing at wherever `integrations/webhook_server.py`
is hosted (needs a public HTTPS URL -- a tunnel for local testing, a real
host for production). Every tool call must include the header
`X-Internal-Tool-Secret: <TOOLS_SHARED_SECRET value>` -- the server
rejects anything without it. Check whichever Telnyx assistant config UI
you're using for where to attach a static header to outgoing tool calls.

**Security-critical:** the `phone` parameter passed to these tools must
come from the call's verified caller-ID metadata (what Telnyx itself
reports as the calling number), never from something the AI extracts
from what the caller *says*. If the assistant is configured to let the
caller state their own phone number in conversation and pass that
straight into these tools, anyone could claim to be a different
patient's number and reach that patient's appointment data.

**Identity verification is required on every call, no exceptions.** A
phone call has no equivalent to the SMS path's "we already texted this
exact info to this number" shortcut -- HIPAA's own call-center guidance
is to never rely on caller ID alone and to verify at least two
independent identifiers. So the assistant must call `verify_patient`
first, early in the call, before `get_upcoming_appointments` or
`reschedule_appointment` -- both of those also independently require
`dob` and will fail verification server-side even if somehow called
without it first, but the conversation should ask naturally rather than
relying on that fallback. See `conversation/voice_persona.md` for how
to phrase the ask warmly.

### verify_patient
- **Endpoint:** `POST /tools/verify_patient`
- **Description:** "Verify the caller's identity using their phone number and date of birth, before discussing any appointment details."
- **Parameters:** `{"phone": "string, from verified caller-ID metadata", "dob": "string, date of birth as stated by the caller, e.g. MM/DD/YYYY"}`
- Call this first. If `verified` comes back `false`, do not proceed to the tools below -- ask the caller to double check their date of birth once, and if it fails again, offer to transfer to the front desk.

### get_upcoming_appointments
- **Endpoint:** `POST /tools/get_upcoming_appointments`
- **Description:** "Look up the caller's upcoming appointment(s), once verified."
- **Parameters:** `{"phone": "string", "dob": "string, same value already confirmed via verify_patient"}`

### check_availability
- **Endpoint:** `POST /tools/check_availability`
- **Description:** "Get open appointment slots for a provider on a given day."
- **Parameters:** `{"provider_id": "integer", "day": "ISO date string"}`
- No patient data involved -- doesn't require verification.

### reschedule_appointment
- **Endpoint:** `POST /tools/reschedule_appointment`
- **Description:** "Move an existing appointment to a new confirmed time slot, once verified."
- **Parameters:** `{"phone": "string", "dob": "string", "appointment_id": "integer", "new_start": "ISO datetime", "new_end": "ISO datetime"}`

## Why tools instead of raw call scripting

This keeps the actual scheduling decisions (what's available, what's
booked) coming from `book.py`/`availability.py` -- the same functions
the SMS path uses -- rather than duplicating that logic inside Telnyx's
assistant config. Telnyx's assistant only handles conversation flow and
calls out to these tools when it needs real data.
