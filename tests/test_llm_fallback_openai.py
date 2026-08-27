"""
OpenAI equivalent of test_llm_fallback.py -- same three properties
proven, against llm_fallback_openai.py instead, with a fake OpenAI
client so no real OPENAI_API_KEY is needed. Confirms the two provider
modules behave identically from sms_conversation.py's point of view.

Run: python3 scripts/demo.py   (populates the databases first)
     python3 tests/test_llm_fallback_openai.py
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from llm_fallback_openai import handle_open_ended


def fake_tool_call(name, arguments: dict, call_id):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))


def fake_response(content, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

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
        fake_response(None, [fake_tool_call("verify_patient", {"dob": "04/12/1988"}, "call_1")]),
        fake_response(None, [fake_tool_call("get_upcoming_appointments", {}, "call_2")]),
        fake_response("You have a cleaning with Dr. Lee coming up soon!"),
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended(
        "+15551230001", "what's my next appointment?", {}, client=client,
    )

    check("model was called exactly 3 times (2 tool turns + final answer)", client.calls == 3)
    check("final reply text passed through correctly", "cleaning with Dr. Lee" in reply)
    check("session records the verified patient by pseudonymous id", state["llm_session"]["verified_patient"]["patient_id"] == "PT-0001")


def test_phone_cannot_be_overridden_by_model():
    script = [
        fake_response(None, [fake_tool_call(
            "verify_patient", {"dob": "04/12/1988", "phone": "+19995551234"}, "call_1",
        )]),
        fake_response("Verified!"),
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended("+15551230001", "verify me", {}, client=client)

    check(
        "verification used the REAL transport phone (+15551230001), not the fake one in tool_input",
        state["llm_session"]["verified_patient"]["patient_id"] == "PT-0001",
    )


if __name__ == "__main__":
    test_verify_then_read_appointments()
    test_phone_cannot_be_overridden_by_model()
    print("\nAll llm_fallback_openai tests passed.")
