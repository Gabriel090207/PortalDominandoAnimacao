from urllib.parse import urlencode

from app.services.telegram.config import (
    TELEGRAM_CLIENT_ID,
    TELEGRAM_REDIRECT_URI,
)


def create_telegram_login_url():

    params = {
        "client_id": TELEGRAM_CLIENT_ID,
        "origin": TELEGRAM_REDIRECT_URI,
        "return_to": TELEGRAM_REDIRECT_URI,
        "scope": "openid profile",
        "response_type": "code",
    }

    url = (
        "https://oauth.telegram.org/auth/auth?"
        + urlencode(params)
    )

    return url