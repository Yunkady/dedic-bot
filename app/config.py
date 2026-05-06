from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    bot_token: str
    orders_group_id: int
    sqlite_db_path: str
    support_username: str
    # Platega
    platega_merchant_id: str
    platega_secret: str
    platega_return_url: str
    platega_failed_url: str
    webhook_port: int


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        orders_group_id=int(os.getenv("ORDERS_GROUP_ID", "0")),
        sqlite_db_path=os.getenv("SQLITE_DB_PATH", "data/bot.sqlite3"),
        support_username=os.getenv("SUPPORT_USERNAME", "").lstrip("@"),
        platega_merchant_id=os.getenv("PLATEGA_MERCHANT_ID", ""),
        platega_secret=os.getenv("PLATEGA_SECRET", ""),
        platega_return_url=os.getenv("PLATEGA_RETURN_URL", "https://t.me/"),
        platega_failed_url=os.getenv("PLATEGA_FAILED_URL", "https://t.me/"),
        webhook_port=int(os.getenv("WEBHOOK_PORT", "8080")),
    )