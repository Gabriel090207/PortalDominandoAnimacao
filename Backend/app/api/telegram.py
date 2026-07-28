from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(
    prefix="/telegram",
    tags=["Telegram"]
)


class TelegramUser(BaseModel):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


@router.post("/auth")
async def telegram_auth(user: TelegramUser):

    print("LOGIN TELEGRAM:")
    print(user)

    return {
        "success": True,
        "user": user
    }