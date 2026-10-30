"""Revalidate the combined private stage/SDK content boundary on storage and reads."""

from ai_workshop.labs.rag.executions.agent_trace import (
    MAX_TOTAL_CHARACTERS,
    TRACE_STORAGE_KEY,
    read_agent_trace,
    validate_content_integrity,
)
from ai_workshop.labs.rag.executions.contextualization import storage_contextualization
from ai_workshop.labs.rag.executions.domain import STAGES, StageObservation


def storage_stages(stages: dict[str, object]) -> dict[str, object]:
    safe = dict(stages)
    characters = 0
    for name in STAGES:
        if name not in stages:
            continue
        raw = stages[name]
        if not isinstance(raw, dict) or not any(
            field in raw for field in ("contextualization", "history_selection")
        ):
            # Existing stage payloads are immutable; do not fill legacy defaults on write.
            continue
        stage = StageObservation.model_validate(raw)
        if stage.stage != name:
            raise ValueError("Stage key does not match its observation")
        content = stage.contextualization
        if content is not None:
            content = storage_contextualization(content)
            if content.content_retention == "retained":
                characters += validate_content_integrity((
                    content.instructions, content.input, content.output,
                ))
            safe[name] = {**raw, "contextualization": content.model_dump(mode="json")}
    trace = read_agent_trace(stages)
    if trace is not None:
        safe[TRACE_STORAGE_KEY] = trace.model_dump(mode="json")
        if trace.content_retention == "retained":
            characters += sum(
                validate_content_integrity((span.instructions, span.input, span.output))
                for span in trace.spans
            )
    if characters > MAX_TOTAL_CHARACTERS:
        raise ValueError("Combined execution content exceeds total limit")
    return safe
