from urllib.parse import urlencode
import secrets
import hashlib
import base64

from app.services.telegram.config import (
    TELEGRAM_CLIENT_ID,
    TELEGRAM_REDIRECT_URI,
)


def create_telegram_login_url():

    state = secrets.token_urlsafe(32)

    verifier = secrets.token_urlsafe(64)

    challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(
                verifier.encode()
            ).digest()
        )
        .decode()
        .replace("=", "")
    )

    params = {
        "client_id": TELEGRAM_CLIENT_ID,
        "redirect_uri": TELEGRAM_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }

    return (
        "https://oauth.telegram.org/auth?"
        + urlencode(params)
    )