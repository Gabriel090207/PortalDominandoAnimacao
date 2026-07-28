from fastapi import APIRouter

from app.services.telegram.oauth import create_telegram_login_url


router = APIRouter(
    prefix="/telegram",
    tags=["Telegram"],
)


@router.get("/login")
async def telegram_login():
    url = create_telegram_login_url()

    return {
        "url": url
    }