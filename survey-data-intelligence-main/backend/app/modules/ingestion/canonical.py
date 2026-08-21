"""Generic canonical schema. Survey-specific field maps belong in a later phase."""

from dataclasses import dataclass, field

CANONICAL_SCHEMA_VERSION = "v1"

MISSING_TOKENS = frozenset(
    {
        "",
        "na",
        "n/a",
        "null",
        "none",
        "nan",
        "-",
        ".",
    }
)


@dataclass(frozen=True)
class CanonicalSchemaConfig:
    schema_version: str = CANONICAL_SCHEMA_VERSION
    drop_empty_columns: bool = False
    column_aliases: dict[str, str] = field(default_factory=dict)


DEFAULT_SCHEMA = CanonicalSchemaConfig()
