from urllib.parse import urlencode

from app.services.telegram.config import (
    TELEGRAM_BOT_ID,
    TELEGRAM_REDIRECT_URI,
)


def create_telegram_login_url():

    params = {
        "bot_id": TELEGRAM_BOT_ID,

        "origin": "https://portaldominandoanimacao.netlify.app",

        "return_to": TELEGRAM_REDIRECT_URI,
    }

    return (
        "https://oauth.telegram.org/auth?"
        + urlencode(params)
    )