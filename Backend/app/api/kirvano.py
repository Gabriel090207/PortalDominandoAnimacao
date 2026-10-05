"""Temporary diagnostics only: no authentication or commercial side effects."""
import json
import logging
import re

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger("uvicorn.error.kirvano_diagnostic")
MAX_BODY_BYTES = 64 * 1024
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9a-z-]{1,128}\Z")
_METADATA_VALUE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_AUTH_MARKERS = ("auth", "token", "secret", "signature", "api-key", "apikey", "api_key", "cookie")


def _reject_json_constant(value: str):
    raise ValueError("Non-standard JSON constant")


@router.post("/kirvano")
async def receive_kirvano_diagnostic(request: Request):
    # Intentionally unauthenticated until Kirvano's token transport is confirmed.
    # Never call persistence, grant access or send email from this diagnostic route.
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json" and not (
        media_type.startswith("application/") and media_type.endswith("+json")
    ):
        raise HTTPException(status_code=415, detail="JSON Content-Type required")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body too large")
        body.extend(chunk)
    try:
        payload = json.loads(body, parse_constant=_reject_json_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(status_code=400, detail="Invalid JSON") from None

    # Header values never enter the log record. Unsafe names are omitted.
    names = sorted({name.lower() for name in request.headers.keys() if _HEADER_NAME.fullmatch(name.lower())})
    auth_names = [name for name in names if any(marker in name for marker in _AUTH_MARKERS)]
    metadata = {
        "method": "POST",
        "path": "/webhooks/kirvano",
        "body_bytes": len(body),
        "header_names": names,
        "auth_related_headers_present": bool(auth_names),
        "auth_related_header_names": auth_names,
    }
    if isinstance(payload, dict):
        for key in ("event", "type", "status"):
            value = payload.get(key)
            if isinstance(value, str):
                # Only short enum-like labels; omit arbitrary strings/PII and log injection.
                if _METADATA_VALUE.fullmatch(value):
                    metadata[key] = value
    logger.info("Kirvano diagnostic: %s", json.dumps(metadata, ensure_ascii=True))
    return {"received": True}
