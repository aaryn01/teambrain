"""LLM client. Any OpenAI-compatible endpoint works (Gemini, OpenAI, Groq...)."""
import json
import os
import re
from functools import lru_cache

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI

load_dotenv()

MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash")
# Tried in order when the main model is overloaded (HTTP 429/503) or unavailable.
FALLBACK_MODELS = [m.strip() for m in os.getenv("LLM_FALLBACK_MODELS", "").split(",") if m.strip()]
# Lower thinking = much faster tool calls. Leave empty for providers that don't support it.
REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "").strip()


@lru_cache(maxsize=1)
def client() -> OpenAI:
    return OpenAI(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL") or None,
        timeout=60,
        max_retries=1,
    )


def chat(messages, tools=None, json_mode=False):
    last_error = None
    for model in [MODEL, *FALLBACK_MODELS]:
        kwargs = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if REASONING_EFFORT:
            kwargs["reasoning_effort"] = REASONING_EFFORT
        try:
            return client().chat.completions.create(**kwargs).choices[0].message
        except APIStatusError as exc:
            if exc.status_code not in (404, 429, 500, 503):
                raise
            last_error = exc
        except APIConnectionError as exc:
            last_error = exc
    raise last_error


def parse_json(text: str) -> dict:
    """Parse a JSON object, tolerating ```json fences around it."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])
