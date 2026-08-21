from fastapi import APIRouter

from app.modules.ai.health import check_ai_health
from app.modules.ai.schemas import AIHealthResponse

_STATUSES = set(AIHealthResponse.model_fields["status"].annotation.__args__)

router = APIRouter(tags=["ai"])


@router.get("/ai/health", response_model=AIHealthResponse)
def ai_health() -> AIHealthResponse:
    payload = check_ai_health()
    status = payload["status"] if payload["status"] in _STATUSES else "provider_error"
    return AIHealthResponse(
        configured=bool(payload["configured"]),
        provider_reachable=bool(payload["provider_reachable"]),
        model_configured=bool(payload["model_configured"]),
        status=status,
    )
