"""
OpenAI equivalent of llm_fallback.py -- same job (SMS open-ended
fallback), same shared tool logic (llm_tools.py), different SDK message
format and tool-call loop mechanics. sms_conversation.py picks between
this and llm_fallback.py via the LLM_PROVIDER environment variable.

Requires OPENAI_API_KEY in the environment. Same BAA rule as Anthropic:
not needed for testing against fake/TUTOR data, required before this
ever touches real PracticeWorks (PWORKS) data -- request one from
OpenAI at baa@openai.com before that point, and use zero-data-retention
API endpoints once it's in place (see docs/pre_launch_checklist.md).

MODEL below is a budget-tier choice for a small practice's call volume
-- verify it's still current in OpenAI's model list before relying on
it long-term; model names/tiers shift over time.
"""
import json

import openai

from llm_tools import TOOL_DEFINITIONS, execute_tool, system_prompt, SMS_ADAPTATION

MODEL = "gpt-5-nano"
MAX_TOOL_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 20

TOOLS = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
    for t in TOOL_DEFINITIONS
]


def handle_open_ended(phone: str, text: str, state: dict, client: "openai.OpenAI | None" = None) -> tuple[str, dict]:
    """Same contract as llm_fallback.handle_open_ended -- `client` is
    injectable so tests can pass a fake one without a real API key,
    see tests/test_llm_fallback_openai.py."""
    client = client or openai.OpenAI()
    state = dict(state)
    session = state.setdefault("llm_session", {})
    history = state.setdefault("llm_history", [])

    history.append({"role": "user", "content": text})
    history[:] = history[-MAX_HISTORY_MESSAGES:]

    messages = [{"role": "system", "content": system_prompt(SMS_ADAPTATION)}] + list(history)
    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.chat.completions.create(model=MODEL, tools=TOOLS, messages=messages)
        message = response.choices[0].message

        if not message.tool_calls:
            final_text = message.content or ""
            history.append({"role": "assistant", "content": final_text})
            return final_text, state

        messages.append({"role": "assistant", "content": message.content, "tool_calls": message.tool_calls})
        for call in message.tool_calls:
            tool_input = json.loads(call.function.arguments) if call.function.arguments else {}
            result = execute_tool(call.function.name, tool_input, phone, session)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": str(result)})

    # Hit MAX_TOOL_ITERATIONS without a final answer -- don't loop forever.
    fallback = "Let me have our front-desk team follow up on that directly."
    history.append({"role": "assistant", "content": fallback})
    return fallback, state
