# Data retention & disposal policy — DRAFT

**This is a starting template, not a finished policy.** It needs review
and adoption by the practice (and ideally a healthcare privacy
attorney, given the CMIA/HIPAA overlap already flagged elsewhere) —
this document exists so that review starts from a concrete draft
instead of a blank page, not as a substitute for that review.

## What data this system creates, and what it actually is

| Store | What it holds | Is it "the medical record"? |
|---|---|---|
| `identity_lookup.db` | Real name, phone, DOB, mapped to a pseudonymous patient_id | No — a pointer to identity, not clinical/appointment history itself |
| `mirror.db` | Appointment times, providers, status — keyed by pseudonymous patient_id only | No — a working copy of scheduling data, not the authoritative record (PracticeWorks/PWORKS is) |
| `audit_log.db` (`access_log` table) | Who/what accessed which patient's data, when, success/failure | No — an access log, required by HIPAA's audit control requirement |
| `audit_log.db` (`llm_call_metrics` table) | Per-API-call latency and estimated cost, no patient data | No — pure operational metrics |
| `conversation_state.db` | In-progress SMS conversation state (verified patient, offered slots) — short-lived by design (30 min TTL) | No — ephemeral working state, not a record of anything historical |

**The authoritative medical/appointment record remains PracticeWorks
itself.** Everything in this list is either a working copy, a pointer,
or an operational log — this matters because it means this system's
retention decisions are about *operational/audit data*, not about the
patient record retention rules the practice already follows for
PracticeWorks itself (which are a separate, already-established policy
this document doesn't replace).

## Proposed retention periods — practice/attorney to confirm each one

- [ ] **`identity_lookup.db` entries**: proposed — retained as long as
      the patient is active in PracticeWorks; a process to remove an
      entry when a patient is fully purged from PracticeWorks itself
      would need to exist (not built yet — see the deletion mechanism
      note below).
- [ ] **`mirror.db` appointment rows**: proposed — since this is a
      working mirror re-synced from PracticeWorks regularly, old rows
      naturally get overwritten on each sync; no separate retention
      decision may be needed here beyond "matches whatever's currently
      in PracticeWorks." Confirm this reasoning holds.
- [ ] **`audit_log.db` access-log entries**: proposed — **[fill in: 6
      years is a common HIPAA-adjacent reference point many
      organizations use for audit logs, but confirm this specific
      number with your attorney rather than treating it as settled]**.
- [ ] **`audit_log.db` LLM cost/latency metrics**: no patient data, no
      compliance-driven retention requirement — proposed: purge after
      **[fill in, e.g. 90 days]** purely to bound disk usage.
- [ ] **`conversation_state.db`**: already auto-expires after 30
      minutes of inactivity by design (see `ROLLOUT_STAGE`/TTL in
      `conversation_store.py`) — likely nothing further needed here,
      confirm.

## Deletion / right-to-erasure mechanism

**Not yet built.** If a patient requests their data be removed from
this system specifically (separate from any request about their actual
PracticeWorks medical record, which follows its own existing process),
there's currently no dedicated "delete this patient's rows" tool. This
should be built once the retention periods above are actually decided
— building deletion logic before knowing what should trigger it isn't
useful yet.

## Who owns this policy going forward

- [ ] Named person/role at the practice responsible for this policy
      once adopted.
- [ ] Review cadence (e.g., annually, or whenever this system's data
      model changes).
