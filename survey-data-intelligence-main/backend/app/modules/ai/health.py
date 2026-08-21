from __future__ import annotations

from typing import Any

from app.config import Settings, settings
from app.modules.ai.config_status import ai_is_configured, ai_model_configured
from app.modules.ai.errors import AIUnavailableError
from app.modules.ai.factory import build_ai_provider

def check_ai_health(
    app_settings: Settings | None = None,
    http_client=None,
    provider=None,
) -> dict[str, Any]:
    cfg = app_settings or settings
    configured = ai_is_configured(cfg)
    model_ok = ai_model_configured(cfg)
    payload = {
        "configured": configured,
        "model_configured": model_ok,
        "provider_reachable": False,
        "status": "not_configured",
    }
    if not configured:
        return payload
    try:
        active = provider if provider is not None else build_ai_provider(cfg, http_client=http_client)
        if active is None:
            return payload
        probe = getattr(active, "probe_health", None)
        if callable(probe):
            probe()
        else:
            active.complete_json(system='Return JSON only: {"ok": true}.', user='{"ping": true}')
        payload["provider_reachable"] = True
        payload["status"] = "ready"
        return payload
    except AIUnavailableError as exc:
        payload["status"] = exc.reason
        payload["provider_reachable"] = exc.reason in {"auth", "rate_limit", "invalid_response"}
        return payload
    except Exception:
        payload["status"] = "provider_error"
        return payload
