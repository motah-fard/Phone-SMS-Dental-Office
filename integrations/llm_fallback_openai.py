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

Retries: not implemented here on purpose, same reasoning as
llm_fallback.py -- the OpenAI SDK already retries transient failures
internally by default.
"""
import json
import sys
import time
from pathlib import Path

import openai

sys.path.insert(0, str(Path(__file__).parent.parent / "mirror_system"))

from llm_tools import TOOL_DEFINITIONS, execute_tool, system_prompt, SMS_ADAPTATION
from audit_log import log_llm_call

MODEL = "gpt-5-nano"
MAX_TOOL_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 20

# $/million tokens, gpt-5-nano -- verify against openai.com/api/pricing
# before trusting this for real financial reporting; prices change.
PRICE_PER_M_INPUT_TOKENS = 0.05
PRICE_PER_M_OUTPUT_TOKENS = 0.40

TOOLS = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
    for t in TOOL_DEFINITIONS
]


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * PRICE_PER_M_INPUT_TOKENS + (output_tokens / 1_000_000) * PRICE_PER_M_OUTPUT_TOKENS


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
        start = time.perf_counter()
        response = client.chat.completions.create(model=MODEL, tools=TOOLS, messages=messages)
        latency_ms = (time.perf_counter() - start) * 1000

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        output_tokens = getattr(usage, "completion_tokens", None) if usage else None
        cost = _estimate_cost(input_tokens, output_tokens) if input_tokens is not None and output_tokens is not None else None
        log_llm_call(
            actor="sms_llm_fallback", provider="openai", model=MODEL, latency_ms=latency_ms,
            input_tokens=input_tokens, output_tokens=output_tokens, estimated_cost_usd=cost,
        )

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
