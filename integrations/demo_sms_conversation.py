"""
Proves sms_conversation.py's state machine works end to end, entirely
locally -- no Telnyx account, no network call, no Flask server needed.
Simulates a full reschedule conversation as a sequence of inbound texts.

Run: python3 scripts/demo.py   (populates the mirror DB first)
     python3 integrations/demo_sms_conversation.py
"""
from sms_conversation import handle_inbound_sms

PHONE = "+15551230001"


def send(text, state):
    print(f"Patient texts: {text!r}")
    reply, state = handle_inbound_sms(PHONE, text, state)
    print(f"Moty replies:   {reply}")
    print()
    return state


def main():
    state = {}
    state = send("RESCHEDULE", state)
    state = send("01/01/1975", state)  # wrong DOB -- Maria's is 1988-04-12
    state = send("04/12/1988", state)  # correct -- verification succeeds, slots offered
    state = send("2", state)
    state = send("YES", state)


if __name__ == "__main__":
    main()
