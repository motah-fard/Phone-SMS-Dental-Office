"""
Renders the SMS templates against real (synthetic) appointment data from
the mirror DB, so you can see actual message text instead of just the
template source. Run scripts/demo.py first to populate the mirror DB.

Run: python3 conversation/demo_messages.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

from book import resolve_patient_by_phone, get_upcoming_appointments
import sms_templates as t


def fmt(dt_str):
    dt = datetime.fromisoformat(dt_str)
    return dt.strftime("%A, %b %d"), dt.strftime("%-I:%M %p")


def main():
    patient = resolve_patient_by_phone("+15551230001", actor="demo_script")
    appts = get_upcoming_appointments(patient["patient_id"], actor="demo_script")
    appt = appts[0]
    date_str, time_str = fmt(appt["start_time"])

    print("--- Appointment reminder ---")
    print(t.appointment_reminder(patient["first_name"], appt["provider_name"], date_str, time_str))
    print()

    print("--- Patient replies YES ---")
    print(t.confirmation_ack(date_str, time_str))
    print()

    print("--- Patient replies RESCHEDULE ---")
    print(t.reschedule_slot_offer(appt["provider_name"], ["Tue 11:00am", "Tue 3:00pm", "Wed 9:30am"]))
    print()

    print("--- Patient picks a new time ---")
    print(t.reschedule_confirmed(appt["provider_name"], "Tuesday, Sep 02", "11:00 AM"))
    print()

    print("--- Missed call follow-up ---")
    print(t.missed_call_followup(patient["first_name"]))


if __name__ == "__main__":
    main()
