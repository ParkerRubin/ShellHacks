from copy import deepcopy
from datetime import datetime

from jsonschema import Draft202012Validator

from .errors import ValidationError
from .privacy import VOCABULARY

SCHEMA_VERSION = "1.0"
MIGRATIONS = {}
BASE = {
    "type": "object",
    "required": ["_id", "schema_version", "private", "key_id"],
    "properties": {
        "_id": {"type": "string", "minLength": 1},
        "schema_version": {"const": SCHEMA_VERSION},
        "private": {"type": "string"},
        "key_id": {"type": "string"},
    },
}
SCHEMAS = {
    name: deepcopy(BASE)
    for name in ("interactions", "user_profiles", "face_signatures")
}
SCHEMAS["interactions"]["required"] += [
    "timestamp",
    "expires_at",
    "session_id",
    "user_id",
    "privacy_level",
    "context",
]
SCHEMAS["interactions"]["properties"].update(
    {
        "user_id": {"type": ["string", "null"]},
        "session_id": {"type": "string"},
        "timestamp": {"type": "string", "format": "date-time"},
        "expires_at": {"type": "string", "format": "date-time"},
        "privacy_level": {"enum": ["public", "personal", "sensitive"]},
        "context": {
            "type": "object",
            "required": ["topics", "entities"],
            "properties": {
                "topics": {"type": "array", "items": {"enum": sorted(VOCABULARY)}},
                "entities": {"type": "array", "maxItems": 0},
            },
        },
        "embedding": {"type": ["array", "null"], "items": {"type": "number"}},
    }
)
SCHEMAS["user_profiles"]["properties"]["updated_at"] = {
    "type": "string",
    "format": "date-time",
}
SCHEMAS["user_profiles"]["required"] += ["updated_at", "consents"]
SCHEMAS["user_profiles"]["properties"]["consents"] = {
    "type": "object",
    "required": ["store_personal_data", "store_face_data", "use_for_personalization"],
    "properties": {
        k: {"type": "boolean"}
        for k in ["store_personal_data", "store_face_data", "use_for_personalization"]
    },
}
SCHEMAS["face_signatures"]["properties"]["user_id"] = {"type": "string", "minLength": 1}
SCHEMAS["face_signatures"]["required"] += ["user_id"]
SCHEMAS["system_config"] = {
    "type": "object",
    "required": ["_id", "schema_version", "settings"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "settings": {"type": "object"},
    },
}


def validate(collection, doc):
    normalized = {
        k: v.isoformat() if isinstance(v, datetime) else v for k, v in doc.items()
    }
    errors = list(
        Draft202012Validator(
            SCHEMAS[collection], format_checker=Draft202012Validator.FORMAT_CHECKER
        ).iter_errors(normalized)
    )
    if errors:
        raise ValidationError(
            f"Invalid {collection} document at {list(errors[0].path)}"
        )


def upgrade(doc):
    result = deepcopy(doc)
    seen = set()
    while result.get("schema_version") != SCHEMA_VERSION:
        version = result.get("schema_version")
        if version in seen or version not in MIGRATIONS:
            raise ValidationError("Unsupported schema version")
        seen.add(version)
        result = MIGRATIONS[version](result)
    return result
