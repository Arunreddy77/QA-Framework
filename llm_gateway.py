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

FRAMEWORK_ROOT = Path(os.environ.get("QA_FRAMEWORK_ROOT", "."))
INSTRUCTIONS_PATH = FRAMEWORK_ROOT / "AGENT_INSTRUCTIONS.md"
SKILLS_DIR = FRAMEWORK_ROOT / "skills"
MODEL = os.environ.get("QA_FRAMEWORK_MODEL", "claude-haiku-4-5-20251001")

_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


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

    response = _client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": json.dumps(input_payload)}],
    )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"{skill_filename} did not return valid JSON: {raw_text[:500]}"
        ) from e

    if isinstance(result, dict) and result.get("escalation"):
        raise SkillEscalation(result)

    return result
