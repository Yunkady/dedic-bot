"""Админ-панель в группе ORDERS_GROUP_ID: команда /admin и inline-кнопки."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from html import escape

from app.config import Settings
from app.labels import status_label
from app.storage import DbOrder, Storage

admin_router = Router(name="admin")

ORDERS_PAGE = 6
USERS_PAGE = 8

_STATUS_FROM_CODE = {
    "w": "waiting_payment",
    "p": "paid_waiting_provision",
    "f": "provisioned",
}


class AdminProvisionState(StatesGroup):
    waiting_credentials = State()


async def _is_group_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in ("creator", "administrator")


async def _guard_message(message: Message, settings: Settings, bot: Bot) -> bool:
    if settings.orders_group_id == 0:
        await message.reply("⚠️ <b>ORDERS_GROUP_ID</b> не задан в настройках.")
        return False
    if message.chat.id != settings.orders_group_id:
        await message.reply(
            "⚠️ Админ-панель доступна только в группе заказов "
            "(совпадает с <b>ORDERS_GROUP_ID</b>)."
        )
        return False
    if message.from_user is None:
        return False
    if not await _is_group_admin(bot, message.chat.id, message.from_user.id):
        await message.reply(
            "⚠️ Нужны права <b>администратора</b> или <b>владельца</b> этой группы."
        )
        return False
    return True


async def _guard_callback(callback: CallbackQuery, settings: Settings, bot: Bot) -> bool:
    if callback.message is None or callback.from_user is None:
        await callback.answer()
        return False
    if settings.orders_group_id == 0 or callback.message.chat.id != settings.orders_group_id:
        await callback.answer("Панель недоступна", show_alert=True)
        return False
    if not await _is_group_admin(bot, callback.message.chat.id, callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return False
    return True


def _dashboard_text(storage: Storage) -> str:
    total = storage.count_orders()
    users_n = storage.count_users()
    rev = storage.revenue_paid_rub()
    by_st = storage.count_orders_by_status()
    lines = [
        "🛠 <b>Админ-панель</b>",
        "",
        f"📦 Заказов в базе: <b>{total}</b>",
        f"👤 Пользователей: <b>{users_n}</b>",
        f"💰 Выручка (оплачено / выдано): <b>{rev}</b> ₽",
        "",
        "📊 <b>По статусам:</b>",
    ]
    if not by_st:
        lines.append("  <i>пока нет данных</i>")
    else:
        for st, n in sorted(by_st.items(), key=lambda x: x[0]):
            lines.append(f"  • {status_label(st)}: <b>{n}</b>")
    lines.extend(["", "Выберите раздел 👇"])
    return "\n".join(lines)


def _dashboard_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="📋 Заказы", callback_data="adm:or:0"))
    b.add(InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:us:0"))
    b.add(InlineKeyboardButton(text="🌍 Статистика по локациям", callback_data="adm:st"))
    b.adjust(1)
    return b


def _stats_text(storage: Storage) -> str:
    rows = storage.stats_sales_by_country()
    if not rows:
        return (
            "🌍 <b>Продажи по локациям</b>\n\n"
            "<i>Нет оплаченных или выданных заказов по странам.</i>"
        )
    lines = [
        "🌍 <b>Продажи по локациям</b>\n",
        "<i>Учитываются статусы «ожидает выдачу» и «выдан».</i>\n",
    ]
    total_cnt = 0
    total_rev = 0
    for _code, name, cnt, rev in rows:
        total_cnt += cnt
        total_rev += rev
        lines.append(
            f"• {escape(name)}: <b>{cnt}</b> шт · <b>{rev}</b> ₽"
        )
    lines.append("")
    lines.append(f"📌 <b>Итого:</b> {total_cnt} заказ(ов), <b>{total_rev}</b> ₽")
    return "\n".join(lines)


def _back_admin_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="◀️ В админку", callback_data="adm:hm"))
    b.adjust(1)
    return b


def _users_page_bounds(storage: Storage, page: int) -> tuple[int, int]:
    total = storage.count_users()
    pages = max(1, (total + USERS_PAGE - 1) // USERS_PAGE)
    page = max(0, min(page, pages - 1))
    return page, pages


def _users_text(storage: Storage, page: int) -> tuple[str, int]:
    page, pages = _users_page_bounds(storage, page)
    offset = page * USERS_PAGE
    users = storage.list_users_admin(USERS_PAGE, offset)
    total = storage.count_users()
    if total == 0:
        return "👥 <b>Пользователи</b>\n\n<i>Пользователей в базе пока нет.</i>", page
    lines = [
        f"👥 <b>Пользователи</b> <i>(стр. {page + 1}/{pages}, всего {total})</i>\n",
    ]
    for uid, uname, bal, oc in users:
        uline = f"@{escape(uname)}" if uname else f"<code>{uid}</code>"
        lines.append(
            f"• {uline}\n"
            f"  id: <code>{uid}</code> · баланс <b>{bal}</b> ₽ · заказов: <b>{oc}</b>"
        )
    return "\n".join(lines), page


def _users_kb(storage: Storage, page: int) -> InlineKeyboardBuilder:
    total = storage.count_users()
    if total == 0:
        b = InlineKeyboardBuilder()
        b.add(InlineKeyboardButton(text="◀️ В админку", callback_data="adm:hm"))
        b.adjust(1)
        return b
    page, pages = _users_page_bounds(storage, page)
    b = InlineKeyboardBuilder()
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"adm:us:{page - 1}")
        )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(text="➡️ След.", callback_data=f"adm:us:{page + 1}")
        )
    if nav:
        b.row(*nav)
    b.add(InlineKeyboardButton(text="◀️ В админку", callback_data="adm:hm"))
    b.adjust(1)
    return b


def _orders_page_bounds(storage: Storage, page: int) -> tuple[int, int]:
    total = storage.count_orders()
    pages = max(1, (total + ORDERS_PAGE - 1) // ORDERS_PAGE)
    page = max(0, min(page, pages - 1))
    return page, pages


def _orders_list(storage: Storage, page: int) -> tuple[str, int, list[DbOrder]]:
    total = storage.count_orders()
    if total == 0:
        return "📋 <b>Заказы</b>\n\n<i>Заказов пока нет.</i>", 0, []
    page, pages = _orders_page_bounds(storage, page)
    offset = page * ORDERS_PAGE
    orders = storage.list_orders_admin(ORDERS_PAGE, offset)
    lines = [
        f"📋 <b>Заказы</b> <i>(стр. {page + 1}/{pages})</i>\n",
    ]
    for o in orders:
        uname = f"@{o.username}" if o.username else str(o.user_id)
        lines.append(
            f"🧾 <b>#{escape(o.order_id)}</b> · {escape(o.country_name)} · "
            f"{o.amount_rub} ₽\n"
            f"   {status_label(o.status)} · {escape(uname)}"
        )
    return "\n".join(lines), page, orders


def _orders_kb(page: int, orders: list[DbOrder], storage: Storage) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for o in orders:
        short_co = o.country_name.replace(" ", "")[:10]
        label = f"#{o.order_id} · {o.amount_rub}₽ · {short_co}"
        if len(label) > 62:
            label = f"#{o.order_id} · {o.amount_rub}₽"
        b.add(
            InlineKeyboardButton(
                text=label,
                callback_data=f"adm:d:{o.payment_id}:{page}",
            )
        )
    b.adjust(1)
    page, pages = _orders_page_bounds(storage, page)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"adm:or:{page - 1}")
        )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(text="➡️ След.", callback_data=f"adm:or:{page + 1}")
        )
    if nav:
        b.row(*nav)
    b.add(InlineKeyboardButton(text="◀️ В админку", callback_data="adm:hm"))
    b.adjust(1)
    return b


def _order_detail_text(o: DbOrder) -> str:
    uname = f"@{escape(o.username)}" if o.username else f"<code>{o.user_id}</code>"
    prov = ""
    if o.provisioned_data:
        prov = (
            f"\n\n🔑 <b>Данные для доступа:</b>\n"
            f"<pre>{escape(o.provisioned_data)}</pre>"
        )
    return (
        f"🧾 <b>Заказ #{escape(o.order_id)}</b>\n\n"
        f"💳 <code>{escape(o.payment_id)}</code>\n"
        f"👤 {uname} · <code>{o.user_id}</code>\n"
        f"📍 {escape(o.country_name)} (<code>{escape(o.country_code)}</code>)\n"
        f"📦 {escape(o.vm_name)}\n"
        f"⚙️ {escape(o.vm_specs)}\n"
        f"💵 <b>{o.amount_rub}</b> ₽\n"
        f"📌 {status_label(o.status)}\n"
        f"🕐 <code>{escape(o.created_at.isoformat())}</code>"
        f"{prov}\n\n"
        "<i>Выдача реквизитов ответом на уведомление в группе по-прежнему доступна.</i>"
    )


def _order_detail_kb(o: DbOrder, page: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.add(
        InlineKeyboardButton(
            text="⏳ Ожидает оплату",
            callback_data=f"adm:s:{o.payment_id}:w:{page}",
        )
    )
    b.add(
        InlineKeyboardButton(
            text="📦 Ожидает выдачу",
            callback_data=f"adm:s:{o.payment_id}:p:{page}",
        )
    )
    b.add(
        InlineKeyboardButton(
            text="✅ Выдан (плейсхолдер)",
            callback_data=f"adm:s:{o.payment_id}:f:{page}",
        )
    )
    b.add(
        InlineKeyboardButton(
            text="📝 Выдать сервер (FSM)",
            callback_data=f"adm:pr:{o.payment_id}:{page}",
        )
    )
    b.add(InlineKeyboardButton(text="◀️ К списку заказов", callback_data=f"adm:or:{page}"))
    b.add(InlineKeyboardButton(text="🏠 Админка", callback_data="adm:hm"))
    b.adjust(1)
    return b


@admin_router.message(Command("admin"))
async def cmd_admin(
    message: Message,
    settings: Settings,
    bot: Bot,
    storage: Storage,
) -> None:
    if not await _guard_message(message, settings, bot):
        return
    await message.answer(
        _dashboard_text(storage),
        reply_markup=_dashboard_kb().as_markup(),
    )


@admin_router.callback_query(F.data == "adm:hm")
async def cb_admin_home(
    callback: CallbackQuery,
    settings: Settings,
    bot: Bot,
    storage: Storage,
) -> None:
    if not await _guard_callback(callback, settings, bot):
        return
    await callback.message.edit_text(
        _dashboard_text(storage),
        reply_markup=_dashboard_kb().as_markup(),
    )
    await callback.answer()


@admin_router.callback_query(F.data == "adm:st")
async def cb_admin_stats(
    callback: CallbackQuery,
    settings: Settings,
    bot: Bot,
    storage: Storage,
) -> None:
    if not await _guard_callback(callback, settings, bot):
        return
    await callback.message.edit_text(
        _stats_text(storage),
        reply_markup=_back_admin_kb().as_markup(),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("adm:us:"))
async def cb_admin_users(
    callback: CallbackQuery,
    settings: Settings,
    bot: Bot,
    storage: Storage,
) -> None:
    if not await _guard_callback(callback, settings, bot):
        return
    page_s = callback.data.split(":")[2]
    try:
        page = int(page_s)
    except ValueError:
        await callback.answer("Ошибка страницы", show_alert=True)
        return
    text, page = _users_text(storage, page)
    await callback.message.edit_text(
        text,
        reply_markup=_users_kb(storage, page).as_markup(),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("adm:or:"))
async def cb_admin_orders(
    callback: CallbackQuery,
    settings: Settings,
    bot: Bot,
    storage: Storage,
) -> None:
    if not await _guard_callback(callback, settings, bot):
        return
    page_s = callback.data.split(":")[2]
    try:
        page = int(page_s)
    except ValueError:
        await callback.answer("Ошибка страницы", show_alert=True)
        return
    text, page, orders = _orders_list(storage, page)
    kb = _orders_kb(page, orders, storage) if orders else _back_admin_kb()
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()


@admin_router.callback_query(F.data.startswith("adm:d:"))
async def cb_admin_order_detail(
    callback: CallbackQuery,
    settings: Settings,
    bot: Bot,
    storage: Storage,
) -> None:
    if not await _guard_callback(callback, settings, bot):
        return
    payload = callback.data.removeprefix("adm:d:")
    try:
        payment_id, page_s = payload.rsplit(":", 1)
        page = int(page_s)
    except ValueError:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    order = storage.get_order(payment_id)
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await callback.message.edit_text(
        _order_detail_text(order),
        reply_markup=_order_detail_kb(order, page).as_markup(),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("adm:s:"))
async def cb_admin_set_status(
    callback: CallbackQuery,
    settings: Settings,
    bot: Bot,
    storage: Storage,
) -> None:
    if not await _guard_callback(callback, settings, bot):
        return
    parts = callback.data.split(":", 4)
    if len(parts) != 5:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    _, _, payment_id, code, page_s = parts
    try:
        page = int(page_s)
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    target = _STATUS_FROM_CODE.get(code)
    if target is None:
        await callback.answer("Неизвестный статус", show_alert=True)
        return
    old = storage.get_order(payment_id)
    if old is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    storage.admin_set_order_status(payment_id, target)
    order = storage.get_order(payment_id)
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await callback.message.edit_text(
        _order_detail_text(order),
        reply_markup=_order_detail_kb(order, page).as_markup(),
    )
    if target == "provisioned" and old.status != "provisioned":
        try:
            body = escape(order.provisioned_data or "")
            await bot.send_message(
                order.user_id,
                "🎉 <b>Заказ отмечен как выдан</b>\n\n"
                f"🧾 #{escape(order.order_id)}\n\n"
                "🔑 <b>Данные:</b>\n"
                f"<pre>{body}</pre>",
            )
        except Exception:
            pass
    await callback.answer("Статус обновлён")


@admin_router.callback_query(F.data.startswith("adm:pr:"))
async def cb_admin_start_provision_fsm(
    callback: CallbackQuery,
    settings: Settings,
    bot: Bot,
    storage: Storage,
    state: FSMContext,
) -> None:
    if not await _guard_callback(callback, settings, bot):
        return
    payload = callback.data.removeprefix("adm:pr:")
    try:
        payment_id, page_s = payload.rsplit(":", 1)
        page = int(page_s)
    except ValueError:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    order = storage.get_order(payment_id)
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await state.set_state(AdminProvisionState.waiting_credentials)
    await state.update_data(
        payment_id=payment_id,
        page=page,
        panel_message_id=callback.message.message_id,
    )
    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.add(InlineKeyboardButton(text="❌ Отменить выдачу", callback_data="adm:pr:cancel"))
    cancel_kb.adjust(1)
    await callback.message.reply(
        "📝 <b>FSM-выдача сервера</b>\n\n"
        f"Заказ: <b>#{escape(order.order_id)}</b>\n"
        "Отправьте следующим сообщением реквизиты доступа.\n\n"
        "Можно прислать многострочный текст (IP, логин, пароль, порт и т.д.).",
        reply_markup=cancel_kb.as_markup(),
    )
    await callback.answer()


@admin_router.callback_query(F.data == "adm:pr:cancel")
async def cb_admin_cancel_provision_fsm(
    callback: CallbackQuery,
    settings: Settings,
    bot: Bot,
    state: FSMContext,
) -> None:
    if not await _guard_callback(callback, settings, bot):
        return
    await state.clear()
    await callback.message.edit_text(
        "❌ Выдача через FSM отменена.",
        reply_markup=_back_admin_kb().as_markup(),
    )
    await callback.answer("Отменено")


@admin_router.message(AdminProvisionState.waiting_credentials)
async def msg_admin_finish_provision_fsm(
    message: Message,
    settings: Settings,
    bot: Bot,
    storage: Storage,
    state: FSMContext,
) -> None:
    if not await _guard_message(message, settings, bot):
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text:
        await message.reply("⚠️ Отправьте текст с реквизитами или нажмите «Отменить выдачу».")
        return
    data = await state.get_data()
    payment_id = str(data.get("payment_id", ""))
    page = int(data.get("page", 0))
    panel_message_id = int(data.get("panel_message_id", 0))
    if not payment_id:
        await state.clear()
        await message.reply("⚠️ Сессия выдачи устарела. Откройте заказ заново.")
        return
    order = storage.get_order(payment_id)
    if order is None:
        await state.clear()
        await message.reply("⚠️ Заказ не найден.")
        return

    storage.set_order_provisioned(payment_id, text)
    order = storage.get_order(payment_id)
    if order is None:
        await state.clear()
        await message.reply("⚠️ Заказ не найден.")
        return
    body = escape(order.provisioned_data or "")
    try:
        await bot.send_message(
            order.user_id,
            "🎉 <b>Ваш сервер готов!</b>\n\n"
            f"🧾 <b>Заказ:</b> #{escape(order.order_id)}\n"
            f"📍 <b>Страна:</b> {escape(order.country_name)}\n"
            f"📦 <b>Тариф:</b> {escape(order.vm_name)}\n"
            f"📌 <b>Статус:</b> {status_label(order.status)}\n\n"
            "🔑 <b>Данные для доступа:</b>\n"
            f"<pre>{body}</pre>",
        )
    except Exception:
        await message.reply("⚠️ Не удалось отправить данные пользователю в ЛС.")

    if panel_message_id:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=panel_message_id,
                text=_order_detail_text(order),
                reply_markup=_order_detail_kb(order, page).as_markup(),
            )
        except Exception:
            pass
    await state.clear()
    await message.reply(
        f"✅ Выдача по заказу <b>#{escape(order.order_id)}</b> завершена через FSM."
    )
