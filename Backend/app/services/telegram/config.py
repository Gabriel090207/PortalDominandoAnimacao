import os

from dotenv import load_dotenv

load_dotenv()


TELEGRAM_CLIENT_ID = os.getenv(
    "TELEGRAM_CLIENT_ID",
    ""
)

TELEGRAM_CLIENT_SECRET = os.getenv(
    "TELEGRAM_CLIENT_SECRET",
    ""
)

TELEGRAM_REDIRECT_URI = os.getenv(
    "TELEGRAM_REDIRECT_URI",
    ""
)

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_BOT_USERNAME = os.getenv(
    "TELEGRAM_BOT_USERNAME",
    ""
)