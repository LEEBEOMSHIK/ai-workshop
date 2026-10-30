from ai_workshop.labs.rag.generation.domain import GenerationProfile
from ai_workshop.labs.rag.generation.execution import GenerationProviderError


def require_generation_budget(
    profile: GenerationProfile, *, prior_model_calls: int = 0,
    prior_reserved_output_tokens: int = 0,
) -> None:
    policy = profile.orchestration
    if policy is None:
        raise GenerationProviderError("orchestration_not_supported", retryable=False)
    generation_calls = 1 if policy.dispatch_mode == "direct_answer" else 2
    if (
        type(prior_model_calls) is not int or prior_model_calls not in {0, 1}
        or type(prior_reserved_output_tokens) is not int or prior_reserved_output_tokens < 0
        or prior_model_calls + generation_calls > policy.max_model_calls
        or prior_reserved_output_tokens + generation_calls * profile.max_output_tokens
        > policy.max_total_output_tokens
    ):
        raise GenerationProviderError("orchestration_budget_exceeded", retryable=False)
