import hashlib
import hmac

from app.services.telegram.config import TELEGRAM_BOT_TOKEN


def verify_telegram_auth(data: dict) -> bool:

    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN não configurado."
        )

    received_hash = data.pop(
        "hash",
        None
    )

    if not received_hash:
        return False


    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(data.items())
    )


    secret_key = hashlib.sha256(
        TELEGRAM_BOT_TOKEN.encode()
    ).digest()


    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()


    return hmac.compare_digest(
        calculated_hash,
        received_hash,
    )