"""
The LLM Gateway, per AGENT_INSTRUCTIONS.md Section 1: stateless, one
completion call per skill invocation. It assembles a prompt from the
binding rulebook + the specific skill.md + the input payload, makes
one call, and returns the parsed result. It holds no memory between
calls -- anything that needs to persist lives in RunState instead.
"""

import os
import json
import functools
from pathlib import Path
import anthropic
import openai

FRAMEWORK_ROOT = Path(os.environ.get("QA_FRAMEWORK_ROOT", "."))
INSTRUCTIONS_PATH = FRAMEWORK_ROOT / "AGENT_INSTRUCTIONS.md"
SKILLS_DIR = FRAMEWORK_ROOT / "skills"

# Which LLM backend to use. Defaults to Anthropic (what this framework was
# designed against); set QA_FRAMEWORK_LLM_PROVIDER to "groq", "gemini", or
# "openrouter" to run against a free-tier provider instead -- e.g. while
# waiting on Anthropic credit. Groq, Gemini, and OpenRouter all expose an
# OpenAI-compatible /chat/completions endpoint, so one code path (the
# `openai` client pointed at a different base_url) covers all three.
PROVIDER = os.environ.get("QA_FRAMEWORK_LLM_PROVIDER", "anthropic").lower()

_PROVIDER_CONFIG = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "default_model": "openai/gpt-oss-120b",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "default_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    },
}

if PROVIDER == "anthropic":
    MODEL = os.environ.get("QA_FRAMEWORK_MODEL", "claude-haiku-4-5-20251001")
    _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
elif PROVIDER in _PROVIDER_CONFIG:
    _cfg = _PROVIDER_CONFIG[PROVIDER]
    MODEL = os.environ.get("QA_FRAMEWORK_MODEL", _cfg["default_model"])
    _client = openai.OpenAI(
        base_url=_cfg["base_url"],
        api_key=os.environ[_cfg["api_key_env"]],
    )
else:
    raise ValueError(
        f"Unknown QA_FRAMEWORK_LLM_PROVIDER '{PROVIDER}' -- expected one of: "
        f"anthropic, {', '.join(_PROVIDER_CONFIG)}"
    )


@functools.lru_cache(maxsize=1)
def _load_instructions() -> str:
    # Cached in-process, but re-read on every process start -- this is
    # what keeps a run traceable to the exact rulebook version it ran
    # under (Section 14 of AGENT_INSTRUCTIONS.md).
    return INSTRUCTIONS_PATH.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=16)
def _load_skill(skill_filename: str) -> str:
    return (SKILLS_DIR / skill_filename).read_text(encoding="utf-8")


class SkillEscalation(Exception):
    """Raised when a skill's output is an escalation rather than a result."""
    def __init__(self, payload: dict):
        self.payload = payload
        super().__init__(payload.get("reason", "escalated"))


def call_skill(skill_filename: str, input_payload: dict) -> dict:
    """
    Assemble the prompt for one skill invocation and call the model once.
    Returns the parsed JSON result. Raises SkillEscalation if the skill
    determined it cannot proceed (per its own escalation triggers).
    """
    system_prompt = (
        _load_instructions()
        + "\n\n---\n\n"
        + _load_skill(skill_filename)
        + "\n\n---\n\n"
        "Respond with ONLY a single JSON object matching the skill's "
        "'Output format' section above, and nothing else -- no preamble, "
        "no markdown fences. If any escalation trigger from the skill "
        "applies, respond instead with exactly this shape: "
        '{"escalation": true, "reason": "...", "blocked_item": "...", '
        '"context": "..."}'
    )

    if PROVIDER == "anthropic":
        response = _client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": json.dumps(input_payload)}],
        )
        raw_text = "".join(
            block.text for block in response.content if block.type == "text"
        )
    else:
        # OpenAI-compatible shape (Groq, Gemini, OpenRouter): system goes
        # in the messages list, and the reply is response.choices[0].
        response = _client.chat.completions.create(
            model=MODEL,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(input_payload)},
            ],
        )
        raw_text = response.choices[0].message.content or ""
        # Some free models wrap JSON in markdown fences despite being told
        # not to -- strip those before parsing rather than failing outright.
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text
            raw_text = raw_text.rsplit("```", 1)[0].strip()
            if raw_text.startswith("json"):
                raw_text = raw_text[4:].strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"{skill_filename} did not return valid JSON: {raw_text[:500]}"
        ) from e

    if isinstance(result, dict) and result.get("escalation"):
        raise SkillEscalation(result)

    return result
