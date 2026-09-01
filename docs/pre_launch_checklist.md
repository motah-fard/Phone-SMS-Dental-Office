# Pre-launch checklist

Everything that needs to happen before real patient data or a real
phone number touches this system. Testing against fake data (what's
built so far) doesn't need any of this — this list is specifically the
gate before go-live. Update this file as items get done or new ones
surface; it's meant to stay current, not be a one-time snapshot.

## PracticeWorks integration
- [x] Get real column names for `Patient File`, `Person file`, and
      `Appointments` from the TUTOR (training) database.
- [x] Confirm the ODBC DSN — `Tutor_DSN`, Pervasive ODBC Client
      Interface driver, confirmed working (32-bit Python required).
- [x] Read-only sync against TUTOR proven working end to end (875 real
      identities, 242 real appointments, correctly pseudonymized).
- [x] Reschedule write-back (UPDATE) proven working against TUTOR,
      confirmed via an independent fresh re-sync.
- [x] New-appointment write-back (INSERT) built — **not yet confirmed
      against TUTOR**, run `scripts/demo_tutor_new_booking_test.py` and
      report the result before checking this off for real.
- [ ] See `docs/pwors_cutover_plan.md` for everything still needed
      before pointing this at the real `PWORKS` database.

## Vendor agreements (BAAs)
- [x] BAA(s) in place (per practice confirmation).
- [ ] Confirm which of the two caller-ID branding options (see
      `docs/caller_id_branding.md`) you're using, and set it up once a
      real Telnyx number exists.

## Legal / regulatory — get an actual healthcare privacy attorney to review
- [ ] California CMIA compliance (stricter than HIPAA in places) —
      not something resolved by this project's own research, needs a
      lawyer's read.
- [ ] California CPPA ADMT regulations — genuinely ambiguous whether
      appointment scheduling counts as a "significant decision"
      requiring pre-use notice/opt-out/risk assessment. Don't guess.
- [ ] Confirm existing SMS/phone consent language explicitly covers
      *automated/AI-generated* contact, not just "texting in general"
      (TCPA implications post the 2024 FCC ruling on AI-generated voice).
- [ ] Update the practice's HIPAA Notice of Privacy Practices and
      patient consent forms to reflect the new automated systems.

## Security
- [ ] Encryption at rest for `mirror.db`, `identity_lookup.db`, and
      `audit_log.db` once these run on the real server (disk encryption
      at minimum — BitLocker on Windows).
- [ ] Restrict OS-level file permissions on those three databases to
      only the service account running this code.
- [ ] TLS/HTTPS in front of `webhook_server.py` — it has none on its
      own (Flask's dev server), needs a reverse proxy or hosting
      platform providing it.
- [ ] Real WSGI server (gunicorn or similar) instead of Flask's dev
      server for anything beyond local testing.
- [ ] Replace in-memory conversation state (`_conversation_state` dict
      in `webhook_server.py`) with a real table — it currently resets
      on every restart and won't work with more than one process.
- [ ] Set up monitoring/alerting for failed SMS sends (currently just a
      print statement — see the `TelnyxError` handling in
      `telnyx_sms_webhook`) and for repeated failed identity
      verifications (a real audit-log signal worth alerting on).
- [ ] Rate limiting on the webhook/tool endpoints (not urgent until real
      call/text volume, but needed before go-live).

## Organizational (the practice's decisions, not code)
- [ ] Security Risk Assessment (SRA) — HIPAA's Security Rule requires
      one; this new system should trigger an update to whatever the
      practice already has, or its first one.
- [ ] Backup/contingency plan for the new databases, documented as part
      of the practice's HIPAA contingency plan.
- [ ] Data retention/disposal policy for `audit_log.db` and old/
      cancelled mirror appointment records — a practice decision, not
      something to decide unilaterally in code.
- [ ] Clarify the AI engineer contractor's own workforce/BAA status
      given direct access to the live PracticeWorks server.
- [ ] **After-hours emergency protocol** — what should Moty say to a
      caller describing a genuine dental emergency when the office is
      closed and no transfer is possible? Needs the practice's actual
      answer (on-call number, answering service, or specific guidance),
      not an invented default. See the flagged TODO in
      `conversation/voice_persona.md`.
- [ ] Decide the exact 15-character CNAM string if going that route
      (see `docs/caller_id_branding.md`) — "DENTAL ARTS PRACTICE" is
      too long and would be auto-truncated.

## Testing / QA
- [ ] Full pilot with fake data (in progress) — voice, SMS, reschedule,
      new booking, verification failure paths, after-hours escalation
      wording.
- [ ] Pilot on a non-critical line (e.g. after-hours overflow) before
      replacing the front desk's main line.
- [ ] Staff training on what the AI can/can't do and how escalations
      reach them.

## Ongoing costs — this is NOT free just because it runs on your own server
Self-hosting avoids cloud hosting fees, but these are real, ongoing,
usage-based costs regardless of where the code runs:
- Telnyx: ~$0.056/min for voice (bundled STT+TTS+orchestration),
  $0.004/message for SMS, ~$0.40/mo per number for CNAM if used.
- Anthropic API: per-token, scales with call/text volume.
- A phone number's base monthly fee through Telnyx.
- If Branded Calling is used instead of CNAM: additional setup/possible
  ongoing cost, quote-based.
Total is usage-based and likely modest for a single small practice, but
give the office a realistic monthly range once real call volume is
known — don't promise "no cost" up front.
