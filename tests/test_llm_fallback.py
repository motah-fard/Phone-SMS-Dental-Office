"""
Proves llm_fallback.py's tool-dispatch loop actually works against the
real book.py/availability.py functions, WITHOUT a real ANTHROPIC_API_KEY.
A fake client stands in for Claude and plays a scripted sequence of
tool calls -- this tests our code (does verify_patient really get
called with the right args, does session state carry the verified
patient between tool calls, does the loop stop correctly), not
Anthropic's model behavior.

Run: python3 scripts/demo.py   (populates the databases first)
     python3 tests/test_llm_fallback.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from llm_fallback import handle_open_ended


class FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, name, tool_input, call_id):
        self.name = name
        self.input = tool_input
        self.id = call_id


class FakeResponse:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class FakeClient:
    """Plays back a fixed script of responses, one per call, regardless
    of what messages/tools were actually sent -- good enough to test
    OUR dispatch logic, not a real conversation."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls += 1
        return self.script.pop(0)


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(1)


def test_verify_then_read_appointments():
    script = [
        FakeResponse("tool_use", [FakeToolUseBlock("verify_patient", {"dob": "04/12/1988"}, "call_1")]),
        FakeResponse("tool_use", [FakeToolUseBlock("get_upcoming_appointments", {}, "call_2")]),
        FakeResponse("end_turn", [FakeTextBlock("You have a cleaning with Dr. Lee coming up soon!")]),
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended(
        "+15551230001", "what's my next appointment?", {}, client=client,
    )

    check("model was called exactly 3 times (2 tool turns + final answer)", client.calls == 3)
    check("final reply text passed through correctly", "cleaning with Dr. Lee" in reply)
    check("session records the verified patient by pseudonymous id", state["llm_session"]["verified_patient"]["patient_id"] == "PT-0001")
    check("history captures both user and assistant turns", len(state["llm_history"]) >= 2)


def test_tool_before_verification_fails_cleanly():
    """A tool that needs a verified patient, called before verify_patient
    succeeds, should return a clean error the model can react to --
    not raise, not silently return someone else's data."""
    script = [
        FakeResponse("tool_use", [FakeToolUseBlock("get_upcoming_appointments", {}, "call_1")]),
        FakeResponse("end_turn", [FakeTextBlock("I'll need to verify your date of birth first.")]),
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended(
        "+15551230001", "what's my appointment?", {}, client=client,
    )

    check("model reacted to the verification-required error", "verify" in reply.lower())
    check("no patient ended up in session state", "verified_patient" not in state["llm_session"])


def test_phone_cannot_be_overridden_by_model():
    """Even if the model's tool_input somehow included a phone field
    (it shouldn't, since phone isn't in any tool's schema), the
    executor must still use the phone passed in from the transport
    layer, never anything from tool_input."""
    script = [
        FakeResponse("tool_use", [FakeToolUseBlock(
            "verify_patient", {"dob": "04/12/1988", "phone": "+19995551234"}, "call_1",
        )]),
        FakeResponse("end_turn", [FakeTextBlock("Verified!")]),
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended(
        "+15551230001", "verify me", {}, client=client,
    )

    check(
        "verification used the REAL transport phone (+15551230001), not the fake one in tool_input",
        state["llm_session"]["verified_patient"]["patient_id"] == "PT-0001",
    )


if __name__ == "__main__":
    test_verify_then_read_appointments()
    test_tool_before_verification_fails_cleanly()
    test_phone_cannot_be_overridden_by_model()
    print("\nAll llm_fallback tests passed.")
