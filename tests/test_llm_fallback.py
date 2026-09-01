"""
Proves llm_fallback.py's tool-dispatch loop actually works against the
real book.py/availability.py functions, WITHOUT a real ANTHROPIC_API_KEY.
A fake client stands in for Claude and plays a scripted sequence of
tool calls -- this tests our code (does verify_patient really get
called with the right args, does session state carry the verified
patient between tool calls, does the loop stop correctly), not
Anthropic's model behavior.

Run: pytest tests/test_llm_fallback.py
"""
from types import SimpleNamespace

from llm_fallback import handle_open_ended
import audit_log


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
    def __init__(self, stop_reason, content, input_tokens=100, output_tokens=20):
        self.stop_reason = stop_reason
        self.content = content
        # Real Anthropic responses always carry usage -- default to a
        # realistic value so every test exercises the cost/latency
        # logging path, not just the ones that check it explicitly.
        self.usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


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


def test_verify_then_read_appointments(fresh_db):
    script = [
        FakeResponse("tool_use", [FakeToolUseBlock("verify_patient", {"dob": "04/12/1988"}, "call_1")]),
        FakeResponse("tool_use", [FakeToolUseBlock("get_upcoming_appointments", {}, "call_2")]),
        FakeResponse("end_turn", [FakeTextBlock("You have a cleaning with Dr. Lee coming up soon!")]),
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended(
        "+15551230001", "what's my next appointment?", {}, client=client,
    )

    assert client.calls == 3  # 2 tool turns + final answer
    assert "cleaning with Dr. Lee" in reply
    assert state["llm_session"]["verified_patient"]["patient_id"] == "PT-0001"
    assert len(state["llm_history"]) >= 2


def test_tool_before_verification_fails_cleanly(fresh_db):
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

    assert "verify" in reply.lower()
    assert "verified_patient" not in state["llm_session"]


def test_phone_cannot_be_overridden_by_model(fresh_db):
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

    reply, state = handle_open_ended("+15551230001", "verify me", {}, client=client)

    # Verification used the REAL transport phone (+15551230001), not the fake one in tool_input.
    assert state["llm_session"]["verified_patient"]["patient_id"] == "PT-0001"


def test_hits_max_tool_iterations_without_looping_forever(fresh_db):
    """If the (fake) model just keeps calling tools and never gives a
    final answer, the loop must bail out with a fallback message rather
    than spin indefinitely."""
    from llm_fallback import MAX_TOOL_ITERATIONS
    script = [
        FakeResponse("tool_use", [FakeToolUseBlock("check_staffed_hours", {}, f"call_{i}")])
        for i in range(MAX_TOOL_ITERATIONS)
    ]
    client = FakeClient(script)

    reply, state = handle_open_ended("+15551230001", "are you open?", {}, client=client)

    assert "front-desk team" in reply
    assert client.calls == MAX_TOOL_ITERATIONS


def test_history_is_capped_on_a_long_running_thread(fresh_db):
    from llm_fallback import MAX_HISTORY_MESSAGES
    state = {"llm_history": [{"role": "user", "content": f"msg {i}"} for i in range(30)]}
    client = FakeClient([FakeResponse("end_turn", [FakeTextBlock("ok")])])

    _, state = handle_open_ended("+15551230001", "one more", state, client=client)

    assert len(state["llm_history"]) <= MAX_HISTORY_MESSAGES + 1


def test_logs_latency_and_estimated_cost_per_api_call(fresh_db):
    """Two tool turns + a final answer = 3 real API calls -- each one
    must get its own metrics row, not one aggregated row per conversation."""
    script = [
        FakeResponse("tool_use", [FakeToolUseBlock("verify_patient", {"dob": "04/12/1988"}, "call_1")],
                     input_tokens=500, output_tokens=30),
        FakeResponse("tool_use", [FakeToolUseBlock("get_upcoming_appointments", {}, "call_2")],
                     input_tokens=600, output_tokens=25),
        FakeResponse("end_turn", [FakeTextBlock("You're all set!")], input_tokens=650, output_tokens=15),
    ]
    client = FakeClient(script)

    handle_open_ended("+15551230001", "what's my next appointment?", {}, client=client)

    rows = audit_log.read_recent_llm_calls(limit=10)
    assert len(rows) == 3
    timestamp, actor, provider, model, latency_ms, input_tokens, output_tokens, cost = rows[0]
    assert actor == "sms_llm_fallback"
    assert provider == "anthropic"
    assert model == "claude-sonnet-5"
    assert latency_ms >= 0
    assert input_tokens == 650 and output_tokens == 15
    # 650 * 2/1e6 + 15 * 10/1e6 = 0.0013 + 0.00015 = 0.00145
    assert abs(cost - 0.00145) < 1e-9
