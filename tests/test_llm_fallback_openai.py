"""
OpenAI equivalent of test_llm_fallback.py -- same properties proven,
against llm_fallback_openai.py instead, with a fake OpenAI client so no
real OPENAI_API_KEY is needed. Confirms the two provider modules behave
identically from sms_conversation.py's point of view.

Run: pytest tests/test_llm_fallback_openai.py
"""
import json
from types import SimpleNamespace

from llm_fallback_openai import handle_open_ended
import audit_log


def fake_tool_call(name, arguments: dict, call_id):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))


def fake_response(content, tool_calls=None, prompt_tokens=100, completion_tokens=20):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        return self.script.pop(0)


def test_verify_then_read_appointments(fresh_db):
    script = [
        fake_response(None, [fake_tool_call("verify_patient", {"dob": "04/12/1988"}, "call_1")]),
        fake_response(None, [fake_tool_call("get_upcoming_appointments", {}, "call_2")]),
        fake_response("You have a cleaning with Dr. Lee coming up soon!"),
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended(
        "+15551230001", "what's my next appointment?", {}, client=client,
    )

    assert client.calls == 3
    assert "cleaning with Dr. Lee" in reply
    assert state["llm_session"]["verified_patient"]["patient_id"] == "PT-0001"


def test_phone_cannot_be_overridden_by_model(fresh_db):
    script = [
        fake_response(None, [fake_tool_call(
            "verify_patient", {"dob": "04/12/1988", "phone": "+19995551234"}, "call_1",
        )]),
        fake_response("Verified!"),
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended("+15551230001", "verify me", {}, client=client)

    assert state["llm_session"]["verified_patient"]["patient_id"] == "PT-0001"


def test_tool_before_verification_fails_cleanly(fresh_db):
    script = [
        fake_response(None, [fake_tool_call("get_upcoming_appointments", {}, "call_1")]),
        fake_response("I'll need to verify your date of birth first."),
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended("+15551230001", "what's my appointment?", {}, client=client)

    assert "verify" in reply.lower()
    assert "verified_patient" not in state["llm_session"]


def test_hits_max_tool_iterations_without_looping_forever(fresh_db):
    from llm_fallback_openai import MAX_TOOL_ITERATIONS
    script = [
        fake_response(None, [fake_tool_call("check_staffed_hours", {}, f"call_{i}")])
        for i in range(MAX_TOOL_ITERATIONS)
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended("+15551230001", "are you open?", {}, client=client)

    assert "front-desk team" in reply
    assert client.calls == MAX_TOOL_ITERATIONS


def test_history_is_capped_on_a_long_running_thread(fresh_db):
    from llm_fallback_openai import MAX_HISTORY_MESSAGES
    state = {"llm_history": [{"role": "user", "content": f"msg {i}"} for i in range(30)]}
    client = FakeClient([fake_response("ok")])

    _, state = handle_open_ended("+15551230001", "one more", state, client=client)

    assert len(state["llm_history"]) <= MAX_HISTORY_MESSAGES + 1


def test_logs_latency_and_estimated_cost_per_api_call(fresh_db):
    script = [
        fake_response(None, [fake_tool_call("verify_patient", {"dob": "04/12/1988"}, "call_1")],
                      prompt_tokens=500, completion_tokens=30),
        fake_response("You're all set!", prompt_tokens=650, completion_tokens=15),
    ]
    client = FakeClient(script)

    handle_open_ended("+15551230001", "verify me", {}, client=client)

    rows = audit_log.read_recent_llm_calls(limit=10)
    assert len(rows) == 2
    timestamp, actor, provider, model, latency_ms, input_tokens, output_tokens, cost = rows[0]
    assert actor == "sms_llm_fallback"
    assert provider == "openai"
    assert model == "gpt-5-nano"
    assert latency_ms >= 0
    assert input_tokens == 650 and output_tokens == 15
    # 650 * 0.05/1e6 + 15 * 0.40/1e6 = 0.0000325 + 0.000006 = 0.0000385
    assert abs(cost - 0.0000385) < 1e-9
