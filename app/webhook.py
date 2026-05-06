"""Aiohttp-сервер для приёма callback-уведомлений от Platega."""

from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger(__name__)


def make_webhook_app(
    merchant_id: str,
    secret: str,
    on_confirmed,  # async callable(transaction_id: str, payload: str)
    on_canceled,   # async callable(transaction_id: str)
) -> web.Application:
    app = web.Application()

    async def handle_callback(request: web.Request) -> web.Response:
        # Проверка подписи
        req_merchant = request.headers.get("X-MerchantId", "")
        req_secret = request.headers.get("X-Secret", "")
        if req_merchant != merchant_id or req_secret != secret:
            logger.warning(
                "Platega callback: неверная авторизация (merchant=%s)", req_merchant
            )
            return web.Response(status=401, text="Unauthorized")

        try:
            data = await request.json()
        except Exception as exc:
            logger.error("Platega callback: ошибка парсинга JSON: %s", exc)
            return web.Response(status=400, text="Bad JSON")

        transaction_id = str(data.get("transactionId", ""))
        status = str(data.get("status", ""))
        payload = str(data.get("payload", ""))

        logger.info("Platega callback: transactionId=%s status=%s", transaction_id, status)

        if status == "CONFIRMED":
            await on_confirmed(transaction_id, payload)
        elif status in ("CANCELED", "CHARGEBACKED"):
            await on_canceled(transaction_id)

        return web.Response(status=200, text="OK")

    app.router.add_post("/platega/callback", handle_callback)
    return app