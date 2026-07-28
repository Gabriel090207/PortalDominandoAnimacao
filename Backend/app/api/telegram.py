from fastapi import APIRouter, HTTPException

from app.services.telegram.auth import verify_telegram_auth
from app.services.telegram.config import BOT_USERNAME

router = APIRouter(
    prefix="/telegram",
    tags=["Telegram"],
)

@router.get("/login")
async def telegram_login():
    return {
        "bot_username": BOT_USERNAME,
    }


@router.post("/auth")
async def telegram_auth(user: dict):
    is_valid = verify_telegram_auth(user.copy())

    if not is_valid:
        raise HTTPException(
            status_code=401,
            detail="Autenticação do Telegram inválida."
        )

    return {
        "status": "authenticated",
        "user": user,
    }