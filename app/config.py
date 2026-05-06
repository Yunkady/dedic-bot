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


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        orders_group_id=int(os.getenv("ORDERS_GROUP_ID", "0")),
        sqlite_db_path=os.getenv("SQLITE_DB_PATH", "data/bot.sqlite3"),
        support_username=os.getenv("SUPPORT_USERNAME", "").lstrip("@"),
    )
