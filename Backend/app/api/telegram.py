from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
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
    auth_date: int | None = None
    hash: str | None = None



# inicia login Telegram
@router.get("/login")
async def telegram_login():

    from app.services.telegram.oauth import (
        create_telegram_login_url
    )

    url = create_telegram_login_url()

    return {
        "url": url
    }



# recebe retorno do Telegram
@router.get("/callback")
async def telegram_callback(
    request: Request
):

    code = request.query_params.get(
        "code"
    )

    print(
        "CODE TELEGRAM:",
        code
    )


    if not code:
        return {
            "error": "Código Telegram não recebido"
        }


    return RedirectResponse(
        "https://portaldominandoanimacao.netlify.app/dashboard"
    )



# autenticação do usuário
@router.post("/auth")
async def telegram_auth(
    user: TelegramUser
):

    print(
        "LOGIN TELEGRAM:"
    )

    print(
        user
    )


    return {
        "success": True,
        "user": user
    }