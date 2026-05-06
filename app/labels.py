"""Общие подписи для UI (бот и админка)."""


def status_label(status: str) -> str:
    mapping = {
        "waiting_payment": "⏳ Ожидает оплату",
        "paid_waiting_provision": "📦 Ожидает выдачу",
        "provisioned": "✅ Выдан",
    }
    return mapping.get(status, status)
