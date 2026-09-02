# Security Risk Assessment outline — DRAFT

**This is a scaffold, not a completed SRA.** HIPAA's Security Rule
requires covered entities to conduct a risk assessment, and this new
system should trigger an update to whatever the practice already has
(or its first one, if it doesn't have one yet). A real SRA needs
organizational knowledge — who has access to what, what the practice's
existing safeguards actually are — that a code review alone can't
supply. This outline structures the work; a person at the practice (or
a compliance consultant) needs to actually fill it in.

## 1. Asset inventory — what needs protecting

- [ ] The real PracticeWorks database (`PWORKS`) and the server it
      runs on (`W-SRV-VM-102`).
- [ ] This project's four local databases (`identity_lookup.db`,
      `mirror.db`, `audit_log.db`, `conversation_state.db`) and
      whatever machine they run on.
- [ ] The Telnyx account (phone number, API key, webhook signing key).
- [ ] The Anthropic/OpenAI API key.
- [ ] `TOOLS_SHARED_SECRET` and any other credentials in `.env`.
- [ ] Physical/network access to the server(s) involved.

## 2. Threats and vulnerabilities — what could go wrong

For each asset above, consider (this project's own security work
already addresses several of these in code — noted where relevant):

- [ ] Unauthorized access to the database files directly (mitigated in
      code by pseudonymization + audit logging; NOT yet mitigated by
      encryption at rest or file permissions — both still open).
- [ ] A stolen/leaked API key (Telnyx, Anthropic/OpenAI, or
      `TOOLS_SHARED_SECRET`) — what's the actual rotation process if
      one leaks? Not yet documented anywhere.
- [ ] Someone other than the real patient reaching their data via
      phone/text (mitigated in code: two-factor phone+DOB verification,
      tested).
- [ ] A forged webhook request (mitigated in code: Ed25519 signature
      verification with replay-window protection, tested with a real
      keypair).
- [ ] Physical theft/loss of the server or a backup.
- [ ] An insider (staff, contractor) misusing access — what's the
      practice's existing policy here, and does it cover this new
      system specifically?
- [ ] A vendor-side breach at Telnyx or Anthropic/OpenAI — what does
      each vendor's BAA actually commit them to, and does the practice
      know their breach-notification process?

## 3. Current safeguards already in place (from this project's own work)

- [x] Pseudonymization — no real identity in the scheduling data itself.
- [x] Two-factor identity verification before any disclosure or write.
- [x] Full audit trail of who/what accessed which patient's data.
- [x] Webhook signature verification (tested with a real keypair).
- [x] Shared-secret auth on internal tool endpoints.
- [x] No raw error/exception text ever shown to a caller or texter.
- [ ] Encryption at rest — not yet, needs the real server.
- [ ] TLS in front of the webhook server — config ready
      (`deploy/Caddyfile`), needs a real domain.

## 4. Likelihood / impact rating

For each threat in section 2, the practice (or consultant) should
rate likelihood (low/medium/high) and impact (low/medium/high) — this
is a judgment call based on the practice's actual environment, not
something derivable from the code alone.

## 5. Remediation plan

For anything rated medium/high risk in section 4: what's the fix, who
owns it, and by when? Cross-reference `docs/pre_launch_checklist.md`
and `docs/pwors_cutover_plan.md` — several remediation items are
already tracked there.

## 6. Review cadence

- [ ] Who re-runs this assessment, and how often (HIPAA doesn't mandate
      a fixed interval, but annually or on significant system change
      is the common practice).
