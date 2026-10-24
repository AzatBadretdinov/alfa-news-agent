import json
from pathlib import Path
from datetime import datetime
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/v1/schema.json").read_text(encoding="utf-8"))
FORMATS = FormatChecker()


@FORMATS.checks("date-time")
def datetime_with_zone(value):
    if not isinstance(value, str):
        return True
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def validate(name, value):
    schema = {"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]}
    Draft202012Validator(schema, format_checker=FORMATS).validate(value)
    return value


def envelope(data, request_id, mode="mock", warnings=()):
    return {"meta": {"schema_version": "1.0.0", "request_id": request_id,
                     "mode": mode, "warnings": list(warnings)}, "data": data}
