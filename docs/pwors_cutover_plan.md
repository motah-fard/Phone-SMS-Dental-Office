# Cutover plan: TUTOR → PWORKS (real patient data)

Everything proven so far — reads, reschedule writes, and (pending
confirmation) new-appointment writes — has been against `TUTOR`,
PracticeWorks' training database with fake people in it. This document
is the gate before any of this touches `PWORKS`, the real production
database with real patients. Nothing here should be treated as
optional or skippable to save time — a mistake against `PWORKS` means
a real patient's real appointment.

## Phase 1 — Finish proving the write paths against TUTOR

- [ ] Run `scripts/demo_tutor_new_booking_test.py` and get a clean
      SUCCESS. If it fails, the error will likely name a missing
      required column — iterate on `write_new_appointment()` in
      `source_system/pervasive_odbc_source.py` until it passes.
- [ ] Run the reschedule and new-booking tests a **second and third
      time** on different appointments/patients — one clean pass could
      be luck (e.g., happened not to hit a patient/provider combination
      with an unusual constraint). Consistency across several different
      real rows is the actual bar, not a single green run.
- [ ] Manually inspect the appointments this testing created inside
      TUTOR (via Pervasive Control Center or PracticeWorks itself, not
      just our own re-sync) — confirm they look correct and sane to a
      human who knows the real UI, not just correct from our own code's
      perspective.

## Phase 2 — Read-only against PWORKS first (no writes yet)

- [ ] Create a **separate DSN** for PWORKS (e.g. `PWORKS_DSN`) — never
      reuse `Tutor_DSN` pointed somewhere else; a distinct name makes
      it much harder to accidentally run a test script against the
      wrong database.
- [ ] Point `pervasive_odbc_source.DSN_NAME` at `PWORKS_DSN` **for a
      read-only check only** — run just `read_patients_normalized()`,
      `read_providers_normalized()`, `read_appointments_normalized()`
      and sanity-check the counts and a few real column values against
      what the front desk actually knows about a few real patients.
      This also catches any schema drift between the training copy and
      the live production copy before it matters.
- [ ] Confirm `SOURCE_BACKEND` stays `sqlite` (or unset) during this
      phase — reading real data is fine, but nothing should write yet.

## Phase 3 — The organizational items that must be true before ANY write to PWORKS

These are prerequisites, not nice-to-haves:

- [ ] Legal review completed (CMIA, CPPA ADMT) — see pre_launch_checklist.md.
- [ ] Encryption at rest + TLS in front of the webhook server.
- [ ] A defined data retention/disposal policy.
- [ ] Security Risk Assessment done or updated.
- [ ] Staff at the practice know this is happening and what to expect —
      not a surprise to whoever's at the front desk that morning.

## Phase 4 — The first real write, deliberately low-stakes

Do not go straight from "reads work against PWORKS" to "the AI can
reschedule real patients." Use a real but disposable test case first:

- [ ] Ask the practice to create one throwaway real patient record (or
      identify a genuinely inactive/test patient already in the
      system) specifically for this — reschedule and book against
      *that* record in PWORKS, never a real active patient's real
      appointment, even once.
- [ ] Confirm the change shows up correctly in the actual PracticeWorks
      UI, not just in our own re-sync — the real test is "does the
      front desk see the right thing," not "does our own code agree
      with itself."

## Phase 5 — Staged rollout to real patients

- [ ] Start with the **lowest-consequence action only**: SMS reminder
      confirmations (`YES`) against real patients. This reveals nothing
      new (the reminder already came from the practice) and writes
      nothing — pure read + acknowledgment. Run this alone for a
      trial period before enabling anything that writes.
- [ ] Enable reschedule next, on a **non-critical phone line** (e.g.
      after-hours overflow) rather than the main line, so a mistake
      affects the fewest people and is easiest to catch quickly.
- [ ] Enable new-appointment booking last — it's the newest, least
      battle-tested write path.
- [ ] Only after all of the above have run cleanly for a real trial
      period, consider moving to the practice's main phone line.

## Standing requirement throughout every phase

- [ ] Someone is actually watching `scripts/view_audit_log.py` (or a
      real alerting setup, once built) during each new phase — a
      "SOURCE WRITE FAILED" or repeated failed-verification entry
      needs a human to see it same-day, not get discovered a week later
      by a patient complaint.
- [ ] A clear, agreed rollback plan: if something goes wrong with a
      real patient's real appointment, who at the practice fixes it
      directly in PracticeWorks, and how does this system get paused
      (flip `SOURCE_BACKEND` back, disable the Telnyx webhook, etc.)
      without needing to reach the AI engineer first.

## Explicit go/no-go

Each phase above should end with an explicit decision from the
practice owner or office manager to proceed — not just "the code
worked" from a technical read. This is a business decision about real
patients, not a pure engineering milestone.
