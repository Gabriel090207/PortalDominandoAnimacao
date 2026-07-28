from urllib.parse import urlencode

from app.services.telegram.config import (
    TELEGRAM_BOT_ID,
    TELEGRAM_REDIRECT_URI,
)


def create_telegram_login_url():

    params = {
        "bot_id": TELEGRAM_BOT_ID,
        "origin": TELEGRAM_REDIRECT_URI,
        "return_to": TELEGRAM_REDIRECT_URI,
    }

    return (
        "https://oauth.telegram.org/auth?"
        + urlencode(params)
    )