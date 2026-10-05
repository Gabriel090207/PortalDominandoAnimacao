"""Authenticated reception only; no persistence or commercial side effects."""
import json
import logging
import hmac
import os
from pathlib import Path

from dotenv import load_dotenv

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger("uvicorn.error.kirvano")
MAX_BODY_BYTES = 64 * 1024
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _reject_json_constant(value: str):
    raise ValueError("Non-standard JSON constant")


@router.post("/kirvano")
async def receive_kirvano(request: Request):
    # Token transport confirmed by a real Kirvano request: security-token.
    # Authentication does not grant access or trigger commercial processing.
    load_dotenv(_BACKEND_ROOT / ".env", override=False)
    expected = os.getenv("KIRVANO_WEBHOOK_TOKEN", "")
    received = request.headers.getlist("security-token")
    if (
        not expected.strip()
        or len(received) != 1
        or not hmac.compare_digest(received[0].encode("utf-8"), expected.encode("utf-8"))
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

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
        json.loads(body, parse_constant=_reject_json_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(status_code=400, detail="Invalid JSON") from None

    # Fixed labels and measured size only: never log headers or payload fields.
    logger.info("Kirvano webhook received: method=POST path=/webhooks/kirvano body_bytes=%d", len(body))
    return {"received": True}
