"""
Enforces the staged rollout from docs/pwors_cutover_plan.md as an actual
runtime control, not just a documented intention someone has to
remember to follow manually.

Set via the ROLLOUT_STAGE env var, three stages, each including
everything the previous one allows:

- "confirmations_only": only replying YES to an existing reminder
  works. No fresh disclosure, no writes at all. This is the safest
  possible stage against real patients -- it's a pure read+acknowledge
  of something the practice already sent.
- "reschedule": the above, plus moving an existing appointment.
- "full": the above, plus booking a brand-new appointment (the newest,
  least battle-tested write path).

Defaults to "full" so every existing demo/test keeps working without
having to set anything -- this control matters for a real deployment
against real patients, not for local fake-data testing.
"""
import os

STAGE_ORDER = ["confirmations_only", "reschedule", "full"]
ROLLOUT_STAGE = os.environ.get("ROLLOUT_STAGE", "full").lower()

if ROLLOUT_STAGE not in STAGE_ORDER:
    raise ValueError(f"ROLLOUT_STAGE={ROLLOUT_STAGE!r} is not one of {STAGE_ORDER}")


def is_enabled(capability: str) -> bool:
    """capability: "reschedule" or "booking". Confirmations (YES) have
    no gate -- they're always allowed, at every stage, since they're
    the safest action and the floor every stage builds on."""
    if capability == "reschedule":
        return STAGE_ORDER.index(ROLLOUT_STAGE) >= STAGE_ORDER.index("reschedule")
    if capability == "booking":
        return ROLLOUT_STAGE == "full"
    raise ValueError(f"unknown capability {capability!r}, expected 'reschedule' or 'booking'")
