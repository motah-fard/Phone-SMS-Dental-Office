"""
Proves the brand-new-appointment flow (as opposed to demo_sms_conversation.py,
which only proves rescheduling an existing one) -- and proves the
verification-failure escalation message is business-hours-aware.

Run: python3 scripts/demo.py   (populates the databases first)
     python3 integrations/demo_new_booking.py
"""
from sms_conversation import handle_inbound_sms, MAX_VERIFICATION_ATTEMPTS

PHONE = "+15551230003"  # Aiko Tanaka in the seed data, dob 1992-07-23


def send(text, state):
    print(f"Patient texts: {text!r}")
    reply, state = handle_inbound_sms(PHONE, text, state)
    print(f"Moty replies:   {reply}")
    print()
    return state


def main():
    print("=== Scenario 1: book a brand-new appointment ===")
    state = {}
    state = send("I'd like to book an appointment", state)
    state = send("07/23/1992", state)
    state = send("1", state)

    print("=== Scenario 2: verification fails twice -> escalation mentions actual next staffed time ===")
    state = {}
    state = send("book", state)
    for _ in range(MAX_VERIFICATION_ATTEMPTS):
        state = send("01/01/1900", state)  # deliberately wrong every time


if __name__ == "__main__":
    main()
