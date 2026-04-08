"""Load default judge prompt from project-root prompt.txt."""
from pathlib import Path

from src.llm_judge import DEFAULT_JUDGE_TEMPLATE


def load_prompt_from_file(project_root: Path) -> str:
    path = project_root / "prompt.txt"
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return DEFAULT_JUDGE_TEMPLATE
