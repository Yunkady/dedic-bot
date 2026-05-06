from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, ErrorEvent, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.admin_handlers import admin_router
from app.catalog import COUNTRIES, find_offer, get_offers, is_country_available
from app.config import Settings, get_settings
from app.labels import status_label
from app.legal import (
    PRIVACY_LEAD_HTML,
    PRIVACY_POLICY_URL,
    TERMS_LEAD_HTML,
    TERMS_OF_SERVICE_URL,
)
from app.storage import DbOrder, Storage


class BuyVmState(StatesGroup):
    main_menu = State()
    choosing_country = State()
    choosing_vm = State()
    waiting_topup_amount = State()


router = Router()

MAIN_MENU_TEXT = (
    "🏠 <b>Главное меню</b>\n\n"
    "Выберите действие 👇"
)

WELCOME_TEXT = (
    "👋 <b>Добро пожаловать в Dedic Bot!</b>\n\n"
    "Мы помогаем быстро заказать виртуальный сервер в разных странах, "
    "пополнить внутренний баланс и отслеживать статус выдачи.\n\n"
    "✨ <b>Что можно сделать:</b>\n"
    "• 🌍 выбрать страну и подходящий тариф;\n"
    "• 💰 оплатить заказ с внутреннего баланса (эквайринг подключим позже);\n"
    "• 🖥 смотреть свои заказы и получать данные доступа после выдачи;\n"
    "• 💬 написать в поддержку, если нужна помощь.\n\n"
    "Перед оплатой загляните в <b>«📚 Документы и поддержка»</b> — там политика "
    "конфиденциальности и пользовательское соглашение.\n\n"
    "Приятного пользования! Выберите пункт меню ниже 👇"
)


def welcome_text_for_user(settings: Settings) -> str:
    username = settings.support_username.strip().lstrip("@")
    if not username:
        return WELCOME_TEXT
    return (
        f"{WELCOME_TEXT}\n\n"
        f"💬 <b>Поддержка:</b> @{escape(username)} — также в меню "
        f"«📚 Документы и поддержка» или команда /support."
    )


async def notify_new_paid_order(
    bot: Bot,
    settings: Settings,
    storage: Storage,
    order: DbOrder,
) -> None:
    if settings.orders_group_id == 0:
        return
    username = f"@{order.username}" if order.username else "без username"
    admin_msg = await bot.send_message(
        settings.orders_group_id,
        "🆕 <b>Новый оплаченный заказ</b>\n\n"
        f"🧾 <b>Заказ:</b> #{order.order_id}\n"
        f"👤 <b>Пользователь:</b> {order.user_id} ({username})\n"
        f"📍 <b>Страна:</b> {order.country_name}\n"
        f"📦 <b>Тариф:</b> {order.vm_name}\n"
        f"⚙️ <b>Характеристики:</b> {order.vm_specs}\n"
        f"💵 <b>Сумма:</b> {order.amount_rub} ₽\n"
        f"💳 <b>Payment ID:</b> <code>{order.payment_id}</code>\n"
        f"📌 <b>Статус:</b> {status_label(order.status)}\n\n"
        "✏️ Ответьте на это сообщение данными сервера, чтобы выдать заказ пользователю.",
    )
    storage.link_group_message(admin_msg.message_id, order.payment_id)


async def notify_balance_topup(
    bot: Bot,
    settings: Settings,
    user_id: int,
    username: str | None,
    amount_rub: int,
    new_balance: int,
) -> None:
    if settings.orders_group_id == 0:
        return
    user_label = f"@{username}" if username else "без username"
    await bot.send_message(
        settings.orders_group_id,
        "💰 <b>Пополнение баланса</b>\n\n"
        f"👤 Пользователь: <code>{user_id}</code> ({escape(user_label)})\n"
        f"➕ Сумма: <b>{amount_rub}</b> ₽\n"
        f"🧮 Новый баланс: <b>{new_balance}</b> ₽",
    )


def main_menu_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🛒 Купить сервер", callback_data="menu:buy"))
    builder.add(InlineKeyboardButton(text="💰 Узнать баланс", callback_data="menu:balance"))
    builder.add(InlineKeyboardButton(text="🖥 Мои серверы", callback_data="menu:servers"))
    builder.add(InlineKeyboardButton(text="📚 Документы и поддержка", callback_data="menu:info"))
    builder.adjust(1)
    return builder


def info_menu_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(
            text="🔒 Политика конфиденциальности",
            callback_data="legal:privacy",
        )
    )
    builder.add(
        InlineKeyboardButton(
            text="📜 Пользовательское соглашение",
            callback_data="legal:terms",
        )
    )
    builder.add(InlineKeyboardButton(text="💬 Поддержка", callback_data="legal:support"))
    builder.add(InlineKeyboardButton(text="◀️ В главное меню", callback_data="menu:home"))
    builder.adjust(1)
    return builder


def legal_doc_keyboard(url: str) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📖 Полный текст документа", url=url))
    builder.add(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:info"))
    builder.adjust(1)
    return builder


def support_keyboard(settings: Settings) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    username = settings.support_username.strip().lstrip("@")
    if username:
        builder.add(
            InlineKeyboardButton(
                text="✉️ Написать в Telegram",
                url=f"https://t.me/{username}",
            )
        )
    builder.add(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:info"))
    builder.adjust(1)
    return builder


def support_message_html(settings: Settings) -> str:
    username = settings.support_username.strip().lstrip("@")
    if not username:
        return (
            "💬 <b>Поддержка</b>\n\n"
            "Чтобы здесь отображался контакт оператора, задайте переменную окружения "
            "<code>SUPPORT_USERNAME</code> — Telegram-username без символа @ "
            "(например: <code>my_support</code>).\n\n"
            "После настройки в этом разделе появится кнопка для перехода в личный чат."
        )
    link = f"https://t.me/{username}"
    return (
        "💬 <b>Поддержка</b>\n\n"
        "По вопросам оплаты, заказов, возвратов и доступа к серверу напишите нам "
        "в личные сообщения Telegram:\n"
        f'👉 <a href="{escape(link, quote=True)}">@{escape(username)}</a>\n\n'
        "Мы постараемся ответить в разумный срок. Укажите номер заказа или кратко опишите ситуацию."
    )


def countries_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for code, title in COUNTRIES.items():
        if is_country_available(code):
            builder.add(InlineKeyboardButton(text=title, callback_data=f"country:{code}"))
        else:
            builder.add(
                InlineKeyboardButton(
                    text=f"{title} 🔴 SOLD OUT",
                    callback_data=f"soldout:{code}",
                )
            )
    builder.add(InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:home"))
    builder.adjust(1)
    return builder


def offers_keyboard(country_code: str) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for offer in get_offers(country_code):
        builder.add(
            InlineKeyboardButton(
                text=f"{offer.name} — {offer.price_rub} ₽/мес",
                callback_data=f"offer:{country_code}:{offer.vm_id}",
            )
        )
    builder.add(InlineKeyboardButton(text="◀️ Назад к странам", callback_data="back:countries"))
    builder.add(InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:home"))
    builder.adjust(1)
    return builder


def payment_keyboard(payment_id: str, amount_rub: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(
            text=f"💰 Оплатить с баланса ({amount_rub} ₽)",
            callback_data=f"paybalance:{payment_id}",
        )
    )
    builder.add(
        InlineKeyboardButton(
            text="🔄 Проверить оплату",
            callback_data=f"check:{payment_id}",
        )
    )
    builder.add(InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:home"))
    builder.adjust(1)
    return builder


def balance_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➕ Пополнить баланс", callback_data="balance:topup"))
    builder.add(InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu:home"))
    builder.adjust(1)
    return builder


def _balance_kind_label(kind: str) -> str:
    mapping = {
        "topup": "➕ Пополнение",
        "purchase": "💸 Оплата заказа",
    }
    return mapping.get(kind, kind)


def balance_text(storage: Storage, user_id: int) -> str:
    user_balance = storage.get_user_balance(user_id)
    txs = storage.list_user_balance_transactions(user_id, limit=5)
    lines = [f"💰 <b>Ваш баланс:</b> {user_balance} ₽", "", "🧾 <b>Последние операции:</b>"]
    if not txs:
        lines.append("• <i>Операций пока нет</i>")
    else:
        for tx in txs:
            sign = "+" if tx.delta_rub > 0 else ""
            lines.append(
                f"• {_balance_kind_label(tx.kind)}: <b>{sign}{tx.delta_rub}</b> ₽ "
                f"(баланс: {tx.balance_after_rub} ₽)"
            )
    return "\n".join(lines)


@router.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
    storage: Storage,
    settings: Settings,
) -> None:
    storage.ensure_user(message.from_user.id, message.from_user.username)
    await state.set_state(BuyVmState.main_menu)
    await message.answer(
        welcome_text_for_user(settings),
        reply_markup=main_menu_keyboard().as_markup(),
    )


@router.message(Command("privacy"))
async def cmd_privacy(message: Message) -> None:
    await message.answer(
        PRIVACY_LEAD_HTML,
        reply_markup=legal_doc_keyboard(PRIVACY_POLICY_URL).as_markup(),
    )


@router.message(Command("terms"))
async def cmd_terms(message: Message) -> None:
    await message.answer(
        TERMS_LEAD_HTML,
        reply_markup=legal_doc_keyboard(TERMS_OF_SERVICE_URL).as_markup(),
    )


@router.message(Command("support"))
async def cmd_support(message: Message, settings: Settings) -> None:
    await message.answer(
        support_message_html(settings),
        reply_markup=support_keyboard(settings).as_markup(),
    )


@router.callback_query(F.data == "menu:home")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BuyVmState.main_menu)
    await callback.message.edit_text(
        MAIN_MENU_TEXT,
        reply_markup=main_menu_keyboard().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:info")
async def open_info_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BuyVmState.main_menu)
    await callback.message.edit_text(
        "📚 <b>Документы и поддержка</b>\n\n"
        "Политика конфиденциальности, пользовательское соглашение и контакт поддержки "
        "(обратная связь через личные сообщения в Telegram, без групповых чатов).",
        reply_markup=info_menu_keyboard().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "legal:privacy")
async def show_privacy(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        PRIVACY_LEAD_HTML,
        reply_markup=legal_doc_keyboard(PRIVACY_POLICY_URL).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "legal:terms")
async def show_terms(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        TERMS_LEAD_HTML,
        reply_markup=legal_doc_keyboard(TERMS_OF_SERVICE_URL).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "legal:support")
async def show_support(callback: CallbackQuery, settings: Settings) -> None:
    await callback.message.edit_text(
        support_message_html(settings),
        reply_markup=support_keyboard(settings).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:buy")
async def open_buy_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BuyVmState.choosing_country)
    await callback.message.edit_text(
        "🌍 <b>Выбор локации</b>\n\n"
        "Выберите страну для виртуальной машины:",
        reply_markup=countries_keyboard().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:balance")
async def show_balance(callback: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.set_state(BuyVmState.main_menu)
    await callback.message.edit_text(
        balance_text(storage, callback.from_user.id),
        reply_markup=balance_keyboard().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "balance:topup")
async def ask_topup_amount(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BuyVmState.waiting_topup_amount)
    await callback.message.edit_text(
        "➕ <b>Пополнение баланса</b>\n\n"
        "Введите сумму целым числом (от <b>100</b> до <b>50000</b> ₽):"
    )
    await callback.answer()


@router.message(BuyVmState.waiting_topup_amount)
async def process_topup_amount(
    message: Message,
    state: FSMContext,
    storage: Storage,
    bot: Bot,
    settings: Settings,
) -> None:
    raw_amount = (message.text or "").strip()
    if not raw_amount.isdigit():
        await message.answer("⚠️ Введите сумму цифрами, например: <code>1500</code>")
        return

    amount_rub = int(raw_amount)
    if amount_rub < 100 or amount_rub > 50000:
        await message.answer("⚠️ Сумма должна быть от 100 до 50000 ₽.")
        return

    new_balance = storage.add_user_balance(
        message.from_user.id,
        message.from_user.username,
        amount_rub,
        kind="topup",
        note="manual_topup",
    )
    await state.set_state(BuyVmState.main_menu)
    await message.answer(
        f"✅ Баланс пополнен на <b>{amount_rub}</b> ₽.\n"
        f"💰 Текущий баланс: <b>{new_balance}</b> ₽.",
        reply_markup=main_menu_keyboard().as_markup(),
    )
    await notify_balance_topup(
        bot=bot,
        settings=settings,
        user_id=message.from_user.id,
        username=message.from_user.username,
        amount_rub=amount_rub,
        new_balance=new_balance,
    )


@router.callback_query(F.data == "menu:servers")
async def show_my_servers(callback: CallbackQuery, state: FSMContext, storage: Storage) -> None:
    await state.set_state(BuyVmState.main_menu)
    orders = storage.list_user_orders(callback.from_user.id, limit=10)
    if not orders:
        text = "🖥 <b>Мои серверы</b>\n\nПока нет заказов — загляните в «🛒 Купить сервер»."
    else:
        rows: list[str] = ["🖥 <b>Ваши серверы:</b>"]
        for order in orders:
            rows.append(
                f"• #{order.order_id} | {order.country_name} | {order.vm_name} | "
                f"{status_label(order.status)}"
            )
        text = "\n".join(rows)

    await callback.message.edit_text(text, reply_markup=main_menu_keyboard().as_markup())
    await callback.answer()


@router.callback_query(F.data == "back:countries")
async def back_to_countries(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BuyVmState.choosing_country)
    await callback.message.edit_text(
        "🌍 <b>Выбор локации</b>\n\n"
        "Выберите страну для виртуальной машины:",
        reply_markup=countries_keyboard().as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("soldout:"))
async def sold_out_country_selected(callback: CallbackQuery) -> None:
    await callback.answer("🔴 Эта локация временно недоступна (SOLD OUT).", show_alert=True)


@router.callback_query(F.data.startswith("country:"))
async def country_selected(callback: CallbackQuery, state: FSMContext) -> None:
    _, country_code = callback.data.split(":")
    if country_code not in COUNTRIES:
        await callback.answer("⚠️ Страна недоступна", show_alert=True)
        return
    if not is_country_available(country_code):
        await callback.answer("🔴 Эта локация временно недоступна (SOLD OUT).", show_alert=True)
        return

    await state.update_data(country_code=country_code)
    await state.set_state(BuyVmState.choosing_vm)
    await callback.message.edit_text(
        f"📍 <b>Страна:</b> {COUNTRIES[country_code]}\n\n"
        "Выберите конфигурацию (отсортировано по возрастанию цены):",
        reply_markup=offers_keyboard(country_code).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("offer:"))
async def offer_selected(
    callback: CallbackQuery,
    storage: Storage,
) -> None:
    _, country_code, vm_id = callback.data.split(":")
    offer = find_offer(country_code, vm_id)
    if offer is None:
        await callback.answer("⚠️ Конфигурация недоступна", show_alert=True)
        return

    order_id = str(uuid.uuid4())[:8]
    vm_specs = (
        f"{offer.cpu} vCPU / {offer.ram_gb} GB RAM / "
        f"{offer.disk_gb} GB SSD / {offer.bandwidth_tb} TB трафика"
    )

    payment_id = f"demo-{order_id}"
    order = DbOrder(
        order_id=order_id,
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        country_code=country_code,
        country_name=COUNTRIES[country_code],
        vm_id=offer.vm_id,
        vm_name=offer.name,
        vm_specs=vm_specs,
        amount_rub=offer.price_rub,
        payment_id=payment_id,
        created_at=datetime.now(timezone.utc),
        status="waiting_payment",
        provisioned_data=None,
    )
    storage.create_order(order)

    await callback.message.edit_text(
        "🧾 <b>Заказ сформирован</b>\n\n"
        "💳 Оплата банковской картой пока не подключена — используйте баланс "
        "(пополните в главном меню) или, для проверки сценария, "
        "«🔄 Проверить оплату» (тестовое подтверждение без реального платежа).\n\n"
        f"📍 <b>Страна:</b> {order.country_name}\n"
        f"📦 <b>Тариф:</b> {order.vm_name}\n"
        f"⚙️ <b>Характеристики:</b> {order.vm_specs}\n"
        f"💵 <b>Сумма:</b> {order.amount_rub} ₽\n\n"
        "Выберите действие ниже 👇",
        reply_markup=payment_keyboard(payment_id, order.amount_rub).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("paybalance:"))
async def pay_with_balance(
    callback: CallbackQuery,
    bot: Bot,
    settings: Settings,
    storage: Storage,
    state: FSMContext,
) -> None:
    _, payment_id = callback.data.split(":")
    order = storage.get_order(payment_id)
    if order is None:
        await callback.answer("⚠️ Заказ не найден", show_alert=True)
        return
    if order.user_id != callback.from_user.id:
        await callback.answer("⚠️ Это не ваш заказ", show_alert=True)
        return
    if order.status != "waiting_payment":
        await callback.answer("ℹ️ Этот заказ уже оплачен", show_alert=True)
        return

    if not storage.spend_user_balance(
        callback.from_user.id,
        order.amount_rub,
        kind="purchase",
        note=f"order:{order.order_id}",
    ):
        await callback.answer("⚠️ Недостаточно средств на балансе", show_alert=True)
        return

    storage.update_order_status(order.payment_id, "paid_waiting_provision")
    order = storage.get_order(order.payment_id)
    if order is None:
        await callback.answer("⚠️ Заказ не найден", show_alert=True)
        return
    await state.set_state(BuyVmState.main_menu)
    await callback.message.edit_text(
        "✅ <b>Оплата с баланса выполнена</b>\n\n"
        f"🧾 <b>Заказ:</b> #{order.order_id}\n"
        f"💸 <b>Списано:</b> {order.amount_rub} ₽\n"
        f"💰 <b>Текущий баланс:</b> {storage.get_user_balance(callback.from_user.id)} ₽\n"
        f"📌 <b>Статус:</b> {status_label(order.status)}\n\n"
        "👷 Администратор скоро выдаст данные от виртуальной машины.",
        reply_markup=main_menu_keyboard().as_markup(),
    )
    await notify_new_paid_order(bot, settings, storage, order)
    await callback.answer("✅ Оплачено с баланса")

@router.callback_query(F.data.startswith("check:"))
async def check_payment(
    callback: CallbackQuery,
    bot: Bot,
    settings: Settings,
    storage: Storage,
    state: FSMContext,
) -> None:
    _, payment_id = callback.data.split(":")
    order = storage.get_order(payment_id)
    if order is None:
        await callback.answer("⚠️ Заказ не найден", show_alert=True)
        return

    if order.status in {"paid_waiting_provision", "provisioned"}:
        await callback.answer("✅ Оплата уже подтверждена")
        return

    if payment_id.startswith("demo-"):
        status = "succeeded"
    else:
        await callback.answer(
            "💳 Внешняя оплата сейчас недоступна. Оплатите с баланса или напишите в поддержку.",
            show_alert=True,
        )
        return

    if status != "succeeded":
        await callback.answer("⏳ Платёж ещё не завершён")
        return

    storage.update_order_status(order.payment_id, "paid_waiting_provision")
    order = storage.get_order(order.payment_id)
    if order is None:
        await callback.answer("⚠️ Заказ не найден", show_alert=True)
        return
    await state.set_state(BuyVmState.main_menu)
    await callback.message.edit_text(
        "✅ <b>Оплата подтверждена</b>\n\n"
        f"🧾 <b>Заказ:</b> #{order.order_id}\n"
        f"📍 <b>Страна:</b> {order.country_name}\n"
        f"📦 <b>Тариф:</b> {order.vm_name}\n"
        f"⚙️ <b>Характеристики:</b> {order.vm_specs}\n"
        f"💵 <b>Сумма:</b> {order.amount_rub} ₽\n\n"
        f"📌 <b>Статус:</b> {status_label(order.status)}\n\n"
        "👷 Администратор скоро пришлёт данные для доступа — спасибо за ожидание!",
        reply_markup=main_menu_keyboard().as_markup(),
    )

    await notify_new_paid_order(bot, settings, storage, order)
    await callback.answer("✅ Оплата подтверждена")


@router.message(
    F.reply_to_message,
    F.chat.type.in_({"group", "supergroup"}),
)
async def provision_server_by_reply(
    message: Message,
    bot: Bot,
    settings: Settings,
    storage: Storage,
) -> None:
    if settings.orders_group_id == 0 or message.chat.id != settings.orders_group_id:
        return
    if message.from_user is None:
        return
    if message.reply_to_message is None:
        return

    payment_id = storage.get_payment_id_by_group_message(message.reply_to_message.message_id)
    if payment_id is None:
        return

    order = storage.get_order(payment_id)
    if order is None:
        await message.reply("⚠️ Заказ не найден.")
        return
    if order.status == "provisioned":
        await message.reply("ℹ️ Этот заказ уже выдан пользователю.")
        return
    if not message.text:
        await message.reply(
            "✏️ Отправьте текст с данными сервера ответом на сообщение с заказом."
        )
        return

    storage.set_order_provisioned(payment_id, message.text.strip())
    order = storage.get_order(payment_id)
    if order is None:
        await message.reply("⚠️ Заказ не найден.")
        return

    await bot.send_message(
        order.user_id,
        "🎉 <b>Ваш сервер готов!</b>\n\n"
        f"🧾 <b>Заказ:</b> #{order.order_id}\n"
        f"📍 <b>Страна:</b> {order.country_name}\n"
        f"📦 <b>Тариф:</b> {order.vm_name}\n"
        f"📌 <b>Статус:</b> {status_label(order.status)}\n\n"
        "🔑 <b>Данные для доступа:</b>\n"
        f"{order.provisioned_data}",
    )
    await message.reply(
        f"✅ Выдача выполнена. Статус: {status_label(order.status)}"
    )


@router.error()
async def global_error_handler(event: ErrorEvent) -> bool:
    logging.exception("Unhandled bot error", exc_info=event.exception)
    message = event.update.message if event.update else None
    callback = event.update.callback_query if event.update else None
    if message is not None:
        try:
            await message.answer(
                "⚠️ Произошла непредвиденная ошибка. Уже разбираемся.\n"
                "Попробуйте повторить действие через несколько секунд."
            )
        except Exception:
            pass
    elif callback is not None:
        try:
            await callback.answer("⚠️ Ошибка обработки. Попробуйте ещё раз.", show_alert=True)
        except Exception:
            pass
    return True


def validate_settings(settings: Settings) -> None:
    missing = []
    if not settings.bot_token:
        missing.append("BOT_TOKEN")
    if missing:
        raise ValueError(f"Не заполнены переменные окружения: {', '.join(missing)}")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    validate_settings(settings)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = Storage(settings.sqlite_db_path)
    storage.init_schema()
    dp = Dispatcher(storage=MemoryStorage())

    dp["settings"] = settings
    dp["storage"] = storage
    dp.include_router(admin_router)
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    finally:
        storage.close()


if __name__ == "__main__":
    asyncio.run(main())
