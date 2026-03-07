"""
LLM Judge: run predefined prompt with transcript + knowledge base; return model output.
Uses OpenAI-compatible API (env: OPENAI_BASE_URL, OPENAI_API_KEY, LLM_JUDGE_MODEL).
"""
from dataclasses import dataclass
from typing import Optional

from src.data_aggregation import AssembledRow


# Placeholder prompt; fill placeholders: {{TRANSCRIPT}}, {{KNOWLEDGE_BASE}}
JUDGE_SYSTEM = """You are an expert evaluator for screening calls. Assess the call against the job/screening criteria and provide:
1. Issue category (one short label)
2. Brief comments explaining strengths and issues
3. Pass/Fail or severity if applicable
Be concise and consistent with typical human reviewer style."""

JUDGE_USER_TEMPLATE = """## Knowledge Base (Job / Screening Requirements)
{{KNOWLEDGE_BASE}}

## Call Transcript
{{TRANSCRIPT}}

Evaluate this screening call. Provide: Issue category, Comments, and Pass/Fail or severity."""


def build_judge_prompt(transcript: str, knowledge_base: str) -> str:
    return (
        JUDGE_USER_TEMPLATE.replace("{{TRANSCRIPT}}", transcript or "(No transcript)")
        .replace("{{KNOWLEDGE_BASE}}", knowledge_base or "(No knowledge base)")
    )


@dataclass
class JudgeResult:
    row_number: int
    call_id: str
    raw_output: str
    error: Optional[str] = None


def run_judge(assembled: AssembledRow) -> JudgeResult:
    """Call LLM with transcript + KB; return JudgeResult."""
    try:
        import openai
        from config import OPENAI_API_KEY, OPENAI_BASE_URL, LLM_JUDGE_MODEL

        client = openai.OpenAI(api_key=OPENAI_API_KEY or "sk-placeholder", base_url=OPENAI_BASE_URL)
        prompt = build_judge_prompt(assembled.transcript, assembled.knowledge_base)
        resp = client.chat.completions.create(
            model=LLM_JUDGE_MODEL,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return JudgeResult(row_number=assembled.row_number, call_id=assembled.call_id, raw_output=raw)
    except Exception as e:
        return JudgeResult(
            row_number=assembled.row_number,
            call_id=assembled.call_id,
            raw_output="",
            error=str(e),
        )


def run_judge_for_all(assembled_rows: list[AssembledRow]) -> list[JudgeResult]:
    return [run_judge(a) for a in assembled_rows]
