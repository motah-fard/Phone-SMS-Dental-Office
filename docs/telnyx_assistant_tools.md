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

### get_upcoming_appointments
- **Endpoint:** `POST /tools/get_upcoming_appointments`
- **Description:** "Look up the caller's upcoming appointment(s) by phone number."
- **Parameters:** `{"phone": "string, caller's phone number in E.164 format"}`

### check_availability
- **Endpoint:** `POST /tools/check_availability`
- **Description:** "Get open appointment slots for a provider on a given day."
- **Parameters:** `{"provider_id": "integer", "day": "ISO date string"}`

### reschedule_appointment
- **Endpoint:** `POST /tools/reschedule_appointment`
- **Description:** "Move an existing appointment to a new confirmed time slot."
- **Parameters:** `{"phone": "string", "appointment_id": "integer", "new_start": "ISO datetime", "new_end": "ISO datetime"}`

## Why tools instead of raw call scripting

This keeps the actual scheduling decisions (what's available, what's
booked) coming from `book.py`/`availability.py` -- the same functions
the SMS path uses -- rather than duplicating that logic inside Telnyx's
assistant config. Telnyx's assistant only handles conversation flow and
calls out to these tools when it needs real data.
