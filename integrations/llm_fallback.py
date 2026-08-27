"""
Anthropic (Claude) LLM fallback for SMS replies that don't match a known
deterministic pattern -- see sms_conversation.py's _handle_inbound_sms_unsafe,
which calls handle_open_ended() below as its last resort. Uses the same
warm persona as the voice assistant, with tool access to the real
scheduling functions (llm_tools.py) so it can act, not just chat.

Requires ANTHROPIC_API_KEY in the environment. Testing against fake
data (source_system's simulated PracticeWorks, or the real PracticeWorks
TUTOR training database) does NOT require the Anthropic BAA -- no real
PHI is involved either way. The BAA is required before this ever
touches real PracticeWorks (PWORKS) data.

This is the Anthropic-specific half: the message format and tool-call
loop mechanics are Anthropic's own shape. See llm_fallback_openai.py for
the OpenAI equivalent -- sms_conversation.py picks between them via the
LLM_PROVIDER environment variable. The actual tool logic (llm_tools.py)
is shared and identical either way.

Known limitation: `history` stores raw SDK message dicts (including
tool_use/tool_result blocks), which aren't cleanly JSON-serializable.
Fine for in-memory state today; whoever builds the real persistent
conversation-state store (see pre_launch_checklist.md) will need to
serialize this properly, not just json.dumps() it as-is.
"""
import anthropic

from llm_tools import TOOL_DEFINITIONS, execute_tool, system_prompt, SMS_ADAPTATION

MODEL = "claude-sonnet-5"
MAX_TOOL_ITERATIONS = 5  # hard cap -- never loop forever on a confused tool cycle
MAX_HISTORY_MESSAGES = 20  # caps prompt growth on a long-running thread

TOOLS = [
    {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
    for t in TOOL_DEFINITIONS
]


def handle_open_ended(phone: str, text: str, state: dict, client: "anthropic.Anthropic | None" = None) -> tuple[str, dict]:
    """Entry point sms_conversation.py calls for anything that doesn't
    match a deterministic pattern. `client` is injectable so tests can
    pass a fake one without a real API key -- see tests/test_llm_fallback.py."""
    client = client or anthropic.Anthropic()
    state = dict(state)
    session = state.setdefault("llm_session", {})
    history = state.setdefault("llm_history", [])

    history.append({"role": "user", "content": text})
    history[:] = history[-MAX_HISTORY_MESSAGES:]

    messages = list(history)
    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL, max_tokens=500, system=system_prompt(SMS_ADAPTATION),
            tools=TOOLS, messages=messages,
        )
        if response.stop_reason != "tool_use":
            final_text = "".join(block.text for block in response.content if block.type == "text")
            history.append({"role": "assistant", "content": final_text})
            return final_text, state

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input, phone, session)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(result)})
        messages.append({"role": "user", "content": tool_results})

    # Hit MAX_TOOL_ITERATIONS without a final answer -- don't loop forever.
    fallback = "Let me have our front-desk team follow up on that directly."
    history.append({"role": "assistant", "content": fallback})
    return fallback, state
