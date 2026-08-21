import logging

logger = logging.getLogger("survey_validator.ingestion")

_BLOCKED_FRAGMENTS = (
    "key",
    "secret",
    "token",
    "password",
    "authorization",
    "prompt",
    "response",
    "cookie",
    "bearer",
)


def _safe_fields(**fields: object) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in fields.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in _BLOCKED_FRAGMENTS):
            continue
        if isinstance(value, str) and any(
            marker in value.lower() for marker in ("bearer ", "sk-", "api_key")
        ):
            continue
        safe[key] = value
    return safe


def log_event(event: str, **fields: object) -> None:
    logger.info("%s %s", event, _safe_fields(**fields))


def log_failure(event: str, **fields: object) -> None:
    logger.error("%s %s", event, _safe_fields(**fields))
