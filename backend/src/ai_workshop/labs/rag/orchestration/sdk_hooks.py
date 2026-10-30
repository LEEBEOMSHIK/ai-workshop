from typing import Any

from agents import Agent, RunHooks
from agents.items import TResponseInputItem
from agents.run_context import AgentHookContext, RunContextWrapper
from agents.tool import Tool
from agents.tool_context import ToolContext

from ai_workshop.labs.rag.generation.domain import StructuredGeneration
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.orchestration.domain import (
    ANSWER_TOOL,
    MANAGER,
    RAG_SPECIALISTS,
    SPECIALIST,
    OrchestrationContext,
)
from ai_workshop.labs.rag.orchestration.model_transport import safe_json
from ai_workshop.labs.rag.orchestration.rejections import (
    DelegationRejection,
    DelegationRejectionReason,
    validate_delegation_arguments,
)


def answer_json(output: StructuredGeneration) -> str:
    return safe_json({
        "schema_version": 2, "status": "answered" if output.claims else "insufficient_evidence",
        "claims": [{"text": claim.text, "evidence_ids": [str(i) for i in claim.evidence_ids]}
                   for claim in output.claims],
    })


class ObservationHooks(RunHooks[OrchestrationContext]):
    async def on_agent_start(
        self, context: AgentHookContext[OrchestrationContext], agent: Agent[OrchestrationContext],
    ) -> None:
        state = context.context
        allowed = set(RAG_SPECIALISTS) if state.autonomous else {MANAGER, SPECIALIST}
        if agent.name not in allowed or agent.name in state.agent_spans:
            raise DelegationRejection(DelegationRejectionReason.INVALID_SDK_TRANSITION)
        state.agent_spans[agent.name] = await state.collector.start_span(
            kind="agent", name=agent.name,
            parent_id=(state.delegation_span
                       if state.autonomous or agent.name == SPECIALIST else None),
            instructions=agent.instructions if isinstance(agent.instructions, str) else None,
            input=state.agent_inputs.pop(agent.name, None),
            evidence_refs=state.evidence_refs(),
        )

    async def on_agent_end(
        self, context: AgentHookContext[OrchestrationContext], agent: Agent[OrchestrationContext],
        output: Any,
    ) -> None:
        state = context.context
        if agent.name == SPECIALIST:
            if not isinstance(output, StructuredGeneration):
                raise GenerationProviderError("provider_invalid_response", retryable=False)
            state.child_output = output
        text = answer_json(output) if isinstance(output, StructuredGeneration) else (
            output if isinstance(output, str) else None
        )
        await state.collector.end_span(state.agent_spans[agent.name], output=text)

    async def on_handoff(
        self, context: RunContextWrapper[OrchestrationContext],
        from_agent: Agent[OrchestrationContext], to_agent: Agent[OrchestrationContext],
    ) -> None:
        state = context.context
        if (not state.autonomous or from_agent.name not in state.agent_spans
                or to_agent.name not in RAG_SPECIALISTS or from_agent.name == to_agent.name
                or state.handoff_task is None):
            raise DelegationRejection(DelegationRejectionReason.INVALID_SDK_TRANSITION)
        state.reserve_tool()
        previous = state.agent_spans.pop(from_agent.name)
        task = safe_json({"task": state.handoff_task})
        state.delegation_span = await state.collector.start_span(
            kind="delegation", name=f"transfer_to_{to_agent.name}", parent_id=previous,
            from_agent=from_agent.name, to_agent=to_agent.name, delegation_mode="handoff",
            input_kind="tool_arguments", input=task, evidence_refs=state.evidence_refs(),
        )
        await state.collector.end_span(previous, output=task)
        await state.collector.end_span(state.delegation_span)

    async def on_llm_start(
        self, context: RunContextWrapper[OrchestrationContext], agent: Agent[OrchestrationContext],
        system_prompt: str | None, input_items: list[TResponseInputItem],
    ) -> None:
        # The model transport records the actual HTTP request after SDK conversion.
        context.context.active_agent = agent.name

    async def on_tool_start(
        self, context: RunContextWrapper[OrchestrationContext], agent: Agent[OrchestrationContext],
        tool: Tool,
    ) -> None:
        state = context.context
        if not isinstance(context, ToolContext) or agent.name != MANAGER:
            raise DelegationRejection(DelegationRejectionReason.INVALID_SDK_TRANSITION)
        if context.tool_name != ANSWER_TOOL or not isinstance(context.tool_arguments, str):
            raise DelegationRejection(DelegationRejectionReason.INVALID_SDK_TRANSITION)
        validate_delegation_arguments(context.tool_arguments)
        state.reserve_tool()
        state.delegation_span = await state.collector.start_span(
            kind="delegation", name=ANSWER_TOOL, parent_id=state.agent_spans[MANAGER],
            from_agent=MANAGER, to_agent=SPECIALIST, delegation_mode="as_tool",
            input_kind="tool_arguments", input=context.tool_arguments,
            evidence_refs=state.evidence_refs(),
        )

    async def on_tool_end(
        self, context: RunContextWrapper[OrchestrationContext], agent: Agent[OrchestrationContext],
        tool: Tool, result: object,
    ) -> None:
        state = context.context
        if state.delegation_span is None:
            raise DelegationRejection(DelegationRejectionReason.INVALID_SDK_TRANSITION)
        await state.collector.end_span(
            state.delegation_span, output=result if isinstance(result, str) else None,
        )
