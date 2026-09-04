from pathlib import Path

_PROMPT_FILES = {
    "rag-contextualize-v1": "contextualize-v1.txt",
    "rag-answer-v1": "answer-v1.txt",
}

_PROMPT_VERSIONS = {
    "rag-contextualize-v1": 1,
    "rag-answer-v1": 1,
}


class PromptNotFoundError(ValueError):
    pass


def load_prompt(reference: str) -> str:
    filename = _PROMPT_FILES.get(reference)
    if filename is None:
        raise PromptNotFoundError("The configured generation prompt is not available.")
    return (Path(__file__).with_name("prompts") / filename).read_text(encoding="utf-8").strip()


def prompt_reference_version(reference: str) -> int:
    version = _PROMPT_VERSIONS.get(reference)
    if version is None:
        raise PromptNotFoundError("The configured generation prompt is not available.")
    return version
