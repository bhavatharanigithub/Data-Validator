from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Batch, BatchStatus
from app.modules.ai.errors import AIUnavailableError
from app.modules.ai.factory import build_ai_provider
from app.modules.ai.schemas import EnrichmentPayload
from app.modules.ingestion.logging_utils import log_event, log_failure
from app.modules.sirl.errors import SirlError
from app.modules.sirl.repositories import load_context, upsert_ai_enrichment
from app.modules.sirl.schemas import AiEnrichment, unavailable_enrichment
from app.modules.sirl.selector import ContextSelector

SYSTEM_PROMPT = (
    "You enrich official survey-data profiles with contextual interpretation only. "
    "Do not recompute statistics. Do not invent numbers. "
    "Return a JSON object with keys: contextual_insights, important_relationships, "
    "potential_data_quality_concerns, context_summary, confidence. "
    "confidence must be a number between 0 and 1."
)


def _fallback(reason: str) -> AiEnrichment:
    return unavailable_enrichment(reason)


def _to_available(payload: EnrichmentPayload) -> AiEnrichment:
    return AiEnrichment(
        enabled=True,
        enriched=True,
        status="available",
        reason=None,
        contextual_insights=payload.contextual_insights,
        important_relationships=payload.important_relationships,
        potential_data_quality_concerns=payload.potential_data_quality_concerns,
        context_summary=payload.context_summary,
        confidence=payload.confidence,
    )


def enrich_profile(
    db: Session,
    batch_id: str,
    provider=None,
    require_profiled: bool = True,
) -> AiEnrichment:
    batch = db.scalars(select(Batch).where(Batch.batch_id == batch_id)).first()
    if batch is None:
        raise SirlError("batch not found", status_code=404)
    if require_profiled and batch.status != BatchStatus.PROFILED:
        raise SirlError("batch is not PROFILED", status_code=409)

    context = load_context(db, batch_id)
    if context is None:
        raise SirlError("profile not found for batch", status_code=404)

    active = provider if provider is not None else build_ai_provider()
    if active is None:
        enrichment = _fallback("not_configured")
        upsert_ai_enrichment(db, batch_id, enrichment, model=None)
        log_event("sirl_ai_unavailable", batch_id=batch_id, reason="not_configured")
        return enrichment

    try:
        selected = ContextSelector(max_bytes=settings.ai_max_context_bytes).select(context)
        raw = active.complete_json(
            system=SYSTEM_PROMPT,
            user=json.dumps(selected, default=str),
        )
        payload = EnrichmentPayload.model_validate(raw)
        enrichment = _to_available(payload)
        upsert_ai_enrichment(db, batch_id, enrichment, model=getattr(active, "model", None))
        log_event("sirl_ai_enriched", batch_id=batch_id)
        return enrichment
    except AIUnavailableError as exc:
        enrichment = _fallback(exc.reason)
        upsert_ai_enrichment(db, batch_id, enrichment, model=getattr(active, "model", None))
        log_failure("sirl_ai_unavailable", batch_id=batch_id, reason=exc.reason)
        return enrichment
    except ValidationError:
        enrichment = _fallback("invalid_response")
        upsert_ai_enrichment(db, batch_id, enrichment, model=getattr(active, "model", None))
        log_failure("sirl_ai_unavailable", batch_id=batch_id, reason="invalid_response")
        return enrichment
    except Exception:
        enrichment = _fallback("provider_error")
        upsert_ai_enrichment(db, batch_id, enrichment, model=getattr(active, "model", None))
        log_failure("sirl_ai_unavailable", batch_id=batch_id, reason="provider_error")
        return enrichment
