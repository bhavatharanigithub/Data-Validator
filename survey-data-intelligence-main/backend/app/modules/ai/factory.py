from app.config import Settings, settings
from app.modules.ai.base import AIProvider
from app.modules.ai.config_status import (
    GEMINI_PROVIDER,
    KNOWN_AI_PROVIDERS,
    ai_is_configured,
    normalize_ai_provider,
    resolved_ai_provider,
)
from app.modules.ai.errors import AIUnavailableError
from app.modules.ai.gemini import GEMINI_DEFAULT_BASE_URL, GEMINI_DEFAULT_MODEL, GeminiProvider
from app.modules.ai.provider import ChatCompletionsProvider


def build_ai_provider(
    app_settings: Settings | None = None,
    http_client=None,
) -> AIProvider | None:
    cfg = app_settings or settings
    kind = normalize_ai_provider(cfg)
    if kind and kind not in KNOWN_AI_PROVIDERS:
        raise AIUnavailableError("provider_error", "Unknown AI provider")
    if not ai_is_configured(cfg):
        return None
    selected = resolved_ai_provider(cfg)
    if selected == GEMINI_PROVIDER:
        return GeminiProvider(
            api_key=cfg.ai_api_key,
            model=cfg.ai_model or GEMINI_DEFAULT_MODEL,
            base_url=cfg.ai_base_url or GEMINI_DEFAULT_BASE_URL,
            timeout_seconds=float(cfg.ai_timeout_seconds),
            http_client=http_client,
            max_retries=int(cfg.ai_max_retries),
            retry_backoff_seconds=float(cfg.ai_retry_backoff_ms) / 1000.0,
        )
    return ChatCompletionsProvider(
        base_url=cfg.ai_base_url,
        api_key=cfg.ai_api_key,
        model=cfg.ai_model,
        timeout_seconds=float(cfg.ai_timeout_seconds),
        http_client=http_client,
        max_retries=int(cfg.ai_max_retries),
        retry_backoff_seconds=float(cfg.ai_retry_backoff_ms) / 1000.0,
    )
