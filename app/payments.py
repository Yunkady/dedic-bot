"""Клиент Platega API для создания платежей и проверки статуса."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

BASE_URL = "https://app.platega.io"

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Plategalink:
    transaction_id: str
    redirect: str
    status: str
    expires_in: str


class PlategaClient:
    def __init__(self, merchant_id: str, secret: str) -> None:
        self._merchant_id = merchant_id
        self._secret = secret
        self._headers = {
            "X-MerchantId": merchant_id,
            "X-Secret": secret,
            "Content-Type": "application/json",
        }

    async def create_payment(
        self,
        amount_rub: int,
        description: str,
        return_url: str,
        failed_url: str,
        payload: str = "",
    ) -> Plategalink:
        body = {
            "paymentDetails": {
                "amount": amount_rub,
                "currency": "RUB",
            },
            "description": description,
            "return": return_url,
            "failedUrl": failed_url,
            "payload": payload,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/v2/transaction/process",
                json=body,
                headers=self._headers,
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.error("Platega create_payment error %s: %s", resp.status, text)
                    raise RuntimeError(f"Platega API error {resp.status}: {text}")
                try:
                    data = await resp.json()
                except Exception as exc:
                    logger.error("Platega create_payment bad JSON: %s | body=%s", exc, text)
                    raise RuntimeError(f"Platega API returned invalid JSON: {text}") from exc

        return Plategalink(
            transaction_id=str(data.get("transactionId") or data.get("id") or ""),
            redirect=str(data.get("redirect") or data.get("url") or ""),
            status=str(data.get("status") or ""),
            expires_in=str(data.get("expiresIn") or ""),
        )

    async def get_payment_status(self, transaction_id: str) -> str:
        """Возвращает статус транзакции."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/v2/transaction/{transaction_id}",
                headers=self._headers,
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.error("Platega get_status error %s: %s", resp.status, text)
                    raise RuntimeError(f"Platega API error {resp.status}: {text}")
                try:
                    data = await resp.json()
                except Exception as exc:
                    logger.error("Platega get_status bad JSON: %s | body=%s", exc, text)
                    raise RuntimeError(f"Platega API returned invalid JSON: {text}") from exc
        return str(data.get("status", "UNKNOWN"))