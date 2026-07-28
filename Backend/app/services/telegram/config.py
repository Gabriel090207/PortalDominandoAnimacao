import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")