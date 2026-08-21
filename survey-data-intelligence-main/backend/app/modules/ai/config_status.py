from app.config import Settings, settings

OPENROUTER_PROVIDER = "openrouter"
GEMINI_PROVIDER = "gemini"
KNOWN_AI_PROVIDERS = {OPENROUTER_PROVIDER, GEMINI_PROVIDER}


def normalize_ai_provider(app_settings: Settings | None = None) -> str:
    cfg = app_settings or settings
    return str(cfg.ai_provider or "").strip().lower()


def resolved_ai_provider(app_settings: Settings | None = None) -> str:
    kind = normalize_ai_provider(app_settings)
    if not kind:
        return OPENROUTER_PROVIDER
    return kind


def ai_is_configured(app_settings: Settings | None = None) -> bool:
    cfg = app_settings or settings
    kind = normalize_ai_provider(cfg)
    if kind and kind not in KNOWN_AI_PROVIDERS:
        return bool(cfg.ai_api_key or cfg.ai_base_url or cfg.ai_model)
    if kind == GEMINI_PROVIDER:
        return bool(cfg.ai_api_key)
    return bool(cfg.ai_base_url and cfg.ai_api_key and cfg.ai_model)


def ai_model_configured(app_settings: Settings | None = None) -> bool:
    cfg = app_settings or settings
    if normalize_ai_provider(cfg) == GEMINI_PROVIDER:
        return True
    return bool(cfg.ai_model)
