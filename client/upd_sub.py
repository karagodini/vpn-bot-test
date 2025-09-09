import asyncio, json, requests, time, uuid
from datetime import datetime as dt
from datetime import datetime
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import ClientSession, TCPConnector
from aiogram import Router, F
import aiosqlite
from uuid import uuid4
from aiogram.enums.parse_mode import ParseMode
from bot import bot
from log import logger
from client.menu import get_main_menu, get_back_button
from db.db import Database, get_emails_from_database, get_server_id, update_sum_my, update_sum_ref, add_free_days, get_db_connection
from handlers.config import get_server_data
from pay.prices import *
from pay.payments import (
    create_payment_yookassa,
    check_payment_yookassa, 
    create_paymentupdate, 
    create_payment_robokassa, 
    check_payment_robokassa, 
    create_payment_cryptobot, 
    check_payment_cryptobot, 
    create_payment_tgpay, 
    create_cloudpayments_invoice, 
    check_payment_cloud,
    create_yoomoney_invoice,
    check_yoomoney_payment_status
)
from pay.process_bay import is_valid_email
from db.db import  handle_database_operations
from handlers.states import UpdClient
from pay.promocode import log_promo_code_usage
from pay.pay_metod import PAYMENT_METHODS
from buttons.client import BUTTON_TEXTS
from dotenv import load_dotenv
from admin.notify import GROUP_CHAT_ID
import os

load_dotenv()

EMAIL = os.getenv("EMAIL")
YOOMONEY_CARD = int(os.getenv("YOOMONEY_CARD"))

FIRST_CHECK_DELAY = int(os.getenv("FIRST_CHECK_DELAY", 15))
SUBSEQUENT_CHECK_INTERVAL = int(os.getenv("SUBSEQUENT_CHECK_INTERVAL", 30))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", 15))

PASS2 = os.getenv("PASS2")
SERVEDATABASE = os.getenv("SERVEDATABASE")
FREE_DAYS = os.getenv("FREE_DAYS")
ENABLE_FREE_UPD = os.getenv("ENABLE_FREE_UPD")

router = Router()

async def gather_in_chunks(tasks, chunk_size):
    """
    Разбивает список задач на части и выполняет их параллельно.

    - Разделяет список задач на небольшие группы и выполняет их асинхронно.
    - Возвращает объединённые результаты выполнения задач.
    """
    results = []
    for i in range(0, len(tasks), chunk_size):
        chunk = tasks[i:i + chunk_size]
        results.extend(await asyncio.gather(*chunk))
    return results


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

@router.callback_query(lambda callback_query: callback_query.data == "extend_subscription")
async def handle_get_config2(callback_query: types.CallbackQuery, state: FSMContext):
    telegram_id = callback_query.from_user.id
    logger.info(f"✅ [handle_get_config2] Начало обработки для telegram_id={telegram_id}")

    emails = await get_emails_from_database(telegram_id)
    logger.info(f"📧 [handle_get_config2] Найденные emails: {emails}")

    if not emails:
        logger.error(f"❌ [handle_get_config2] Не найдено email для telegram_id {telegram_id}")
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu"))
        keyboard.adjust(1)
        await callback_query.message.edit_text(
            "❌ Не удалось найти ваши конфигурации.",
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
        return

    # Запускаем from_upd_sub для каждого email → возвращает (text, can_extend)
    responses = await gather_in_chunks([from_upd_sub(email) for email in emails], chunk_size=5)
    logger.info(f"📨 [handle_get_config2] Ответы от from_upd_sub: {responses!r}")

    full_response = []
    keyboard = InlineKeyboardBuilder()

    for email, (text, can_extend) in zip(emails, responses):  # ⬅️ Распаковываем кортеж
        logger.info(f"🔍 [handle_get_config2] email={email}, can_extend={can_extend}, content={text[:200]}...")

        if text and text.strip():
            full_response.append(text)

            # Добавляем кнопки ТОЛЬКО если можно продлевать
            if can_extend:
                keyboard.add(
                    InlineKeyboardButton(
                        text=f"🔑 Продлить подписку",
                        callback_data=f"extend_subscription_{email}"
                    )
                )
            else:
                keyboard.add(
                    InlineKeyboardButton(
                        text="ℹ️ Конфиг не найден",
                        callback_data="notify_support"  # или просто заглушка
                    )
                )

            # Кнопка пробного периода — только если email передан
            try:
                async with aiosqlite.connect("users.db") as conn:
                    # Получаем days_left из user_configs
                    async with conn.execute(
                        "SELECT days_left FROM user_configs WHERE email = ?",
                        (email,)
                    ) as cursor:
                        row = await cursor.fetchone()
                        days_left = row[0] if row else None

                db = Database(USERSDATABASE)
                # Проверяем, использовал ли пользователь пробник
                used_trial = db.has_used_trial_seven(telegram_id)

                # Показываем кнопку ТОЛЬКО если оба условия выполняются
                if days_left == -7 and not used_trial:
                    keyboard.add(
                        InlineKeyboardButton(
                            text="🎁 Пробный период (7 дней)",
                            callback_data=f"trial_seven_{email}"
                        )
                    )

            except Exception as e:
                logger.error(f"🔧 [handle_get_config2] Ошибка проверки условий для {email}: {e}")
        else:
            logger.warning(f"⚠️ [handle_get_config2] Пустой текст для email: {email}")

    keyboard.adjust(1)

    # Инструкции
    instruction_keyboard = InlineKeyboardBuilder()
    instruction_keyboard.add(
        InlineKeyboardButton(text="🍏 IOS", callback_data="show_instruction_ios"),
        InlineKeyboardButton(text="📱 Android", callback_data="show_instruction_android"),
        InlineKeyboardButton(text="💻 MacOS", callback_data="show_instruction_macos"),
        InlineKeyboardButton(text="🖥 Windows", callback_data="show_instruction_windows"),
    )
    instruction_keyboard.adjust(2)

    # Кнопка "Назад"
    main_menu_keyboard = InlineKeyboardBuilder()
    main_menu_keyboard.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu")
    )
    main_menu_keyboard.adjust(1)

    # Собираем всё
    keyboard.attach(instruction_keyboard)
    keyboard.attach(main_menu_keyboard)

    if full_response:
        response_text = "\n\n".join(full_response)
        logger.info(f"📤 [handle_get_config2] Отправляем текст:\n{response_text}")
        await callback_query.message.edit_text(
            response_text,
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
    else:
        logger.warning("📭 [handle_get_config2] full_response пустой — показываем заглушку")
        fallback_kb = InlineKeyboardBuilder()
        fallback_kb.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu"))
        fallback_kb.adjust(1)
        await callback_query.message.edit_text(
            "❌ Не удалось загрузить статус подписок.",
            reply_markup=fallback_kb.as_markup(),
            parse_mode="HTML"
        )

    await state.update_data(emails=emails)

@router.callback_query(lambda c: c.data.startswith("show_instruction_ios"))
async def process_instruction_callback_ios(callback_query: types.CallbackQuery, state: FSMContext):

    instruction_text = (
        "1️⃣ Скачайте приложение на выбор, но советуем на всякий случай скачать все из App Store на случай блокировки приложения.\n\n"
        "<b><a href='https://apps.apple.com/ru/app/v2raytun/id6476628951'>v2RayTun</a></b>:\n"
        "(<a href='https://apps.apple.com/ru/app/v2raytun/id6476628951'>https://apps.apple.com/ru/app/v2raytun/id6476628951</a>)\n\n"
        "<b><a href='https://apps.apple.com/us/app/happ-proxy-utility/id6504287215'>Happ</a></b>:\n"
        "(<a href='https://apps.apple.com/us/app/happ-proxy-utility/id6504287215'>https://apps.apple.com/us/app/happ-proxy-utility/id6504287215</a>)\n\n"
        "<b><a href='https://apps.apple.com/us/app/streisand/id6450534064?platform=iphone'>Streisand</a></b>:\n"
        "(<a href='https://apps.apple.com/us/app/streisand/id6450534064?platform=iphone'>https://apps.apple.com/us/app/streisand/id6450534064?platform=iphone</a>)\n\n"
        "2️⃣ Скопируйте ссылку, нажав на нее ⤴️\n\n"
        "3️⃣ Перейдите в скачанное <b>Вами</b> приложение и активируйте ключ, который скопировали в нашем боте."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Пошаговая инструкция", url="https://telegra.ph/MoyVPN-na-IOS-v2RayTun-04-28")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")]
    ])


    # Отправляем новое сообщение, не удаляя старое
    await callback_query.message.answer(
        instruction_text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith("show_instruction_android"))
async def process_instruction_callback_android(callback_query: types.CallbackQuery, state: FSMContext):

    instruction_text = (
        "1️⃣ Скачайте приложение <b><a href='https://play.google.com/store/search?q=happ&c=apps&hl=ru'>Happ</a></b> из Google Play\n\n"
        "2️⃣ Скопируйте ссылку, нажав на нее\n\n"
        "3️⃣ Перейдите в приложение <b>Happ</b>, нажмите на плюсик в правом верхнем углу "
        "-> \"Добавить из буфера\" и активируйте VPN"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Пошаговая инструкция", url="https://telegra.ph/MoyVPN-na-Android-04-28")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")]
    ])


    # Отправляем новое сообщение, не удаляя старое
    await callback_query.message.answer(
        instruction_text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith("show_instruction_macos"))
async def process_instruction_callback_macos(callback_query: types.CallbackQuery, state: FSMContext):

    instruction_text = (
        "1️⃣ Скачайте приложение <b><a href='https://apps.apple.com/app/id6476628951'>v2RayTun</a></b> из Appstore\n\n"
        "2️⃣ Скопируйте ссылку, нажав на нее\n\n"
        "3️⃣ Перейдите в приложение <b>v2RayTun</b>, нажмите на плюсик в правом верхнем углу "
        "-> \"Добавить из буфера\" и активируйте VPN"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Пошаговая инструкция", url="https://telegra.ph/MoyVPN-na-MacOS-v2RayTun-04-28")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")]
    ])


    # Отправляем новое сообщение, не удаляя старое
    await callback_query.message.answer(
        instruction_text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith("show_instruction_windows"))
async def process_instruction_callback_windows(callback_query: types.CallbackQuery, state: FSMContext):

    instruction_text = (
        "1️⃣ Скачайте приложение <b><a href='https://v2raytun.com/'>V2Ray</a></b>\n\n"
        "2️⃣ Обязательно прочитайте <b>инструкцию по установке</b> по кнопке ниже!\n\n"
        "3️⃣ Перейдите в установленное приложение <b><a href='https://v2raytun.com/'>V2Ray</a></b> на Вашем ПК."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Пошаговая инструкция", url="https://telegra.ph/Nastrojka-V2Ray-na-Windows-MoyVPN-09-02")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")]
    ])


    # Отправляем новое сообщение, не удаляя старое
    await callback_query.message.answer(
        instruction_text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback_query.answer()


async def from_upd_sub(email: str):
    logger.info(f"🔄 [from_upd_sub] Запрос статуса для email={email}")

    db = Database(USERSDATABASE)
    client_server_pairs = await db.get_ids_by_email(email)

    if not client_server_pairs:
        logger.warning(f"🔍 [from_upd_sub] Нет данных для email={email}")
        return f"👤 <b>Ваш айди</b>: {email}\nℹ️ Нет данных о клиенте.", False

    try:
        responses = await gather_in_chunks([
            sub_server(server_id=sid, client_id=cid, email=email)
            for cid, sid in client_server_pairs
        ], chunk_size=5)

        valid_responses = [r for r in responses if r and isinstance(r, tuple)]
        if valid_responses:
            # Берём первый валидный ответ (можно и объединить — зависит от логики)
            text, can_extend = valid_responses[0]
            for r in valid_responses[1:]:
                if isinstance(r, tuple):
                    text += "\n\n" + r[0]
                    can_extend = can_extend or r[1]  # Если хоть на одном сервере можно — разрешаем
            return text, can_extend

    except Exception as e:
        logger.error(f"⚠️ [from_upd_sub] Ошибка при запросе к серверам: {e}", exc_info=True)

    # Fallback
    logger.info(f"🔁 [from_upd_sub] Используем fallback для {email}")
    try:
        async with aiosqlite.connect("users.db") as conn:
            async with conn.execute(
                "SELECT days_left FROM user_configs WHERE email = ?",
                (email,)
            ) as cursor:
                row = await cursor.fetchone()
                days_left = row[0] if row else None

        status = (
            "❌ <b>Ваша подписка закончилась</b>" if days_left is None or days_left <= 0
            else f"📅 Осталось <b>{days_left}</b> дн."
        )
        text = f"👤 <b>Ваш айди</b>: {email}\n{status}"
        can_extend = days_left is not None and days_left > 0  # Можно продлить, если был статус
        return text, can_extend

    except Exception as e:
        logger.error(f"❌ [from_upd_sub] Fallback не удался: {e}", exc_info=True)
        return f"👤 <b>Ваш айди</b>: {email}\n⚠️ Статус неизвестен", False


async def sub_server(server_id, client_id, email):
    """
    Возвращает статус подписки для одного клиента на одном сервере.
    Если не удалось получить данные с сервера (даже если есть кэш) — показываем ошибку.
    Обновляет days_left в user_configs, если данные получены.
    """
    logger.info(f"⚙️ [sub_server] Начало обработки: email={email}, server_id={server_id}, client_id={client_id}")

    # Получаем данные сервера
    logger.debug(f"🌐 [sub_server] Запрашиваем данные сервера server_id={server_id}")
    server_data = await get_server_data(server_id)
    if not server_data:
        logger.warning(f"❌ [sub_server] Не найдены данные для server_id={server_id}. Пропускаем запрос к серверу.")
        server_data = None

    # Шаг 1: Получаем config и days_left из user_configs (кэш)
    config = "❗ Config не найден"
    days_left = None

    try:
        async with aiosqlite.connect("users.db") as conn:
            async with conn.execute(
                "SELECT config, days_left FROM user_configs WHERE email = ?",
                (email,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    config = row[0] if row[0] else config
                    if row[1] is not None:
                        days_left = int(row[1])
                    logger.debug(f"💾 [sub_server] Кэш загружен: config={'есть' if row[0] else 'нет'}, days_left={days_left}")
                else:
                    logger.info(f"🟡 [sub_server] Нет кэша для email={email}")
    except Exception as e:
        logger.error(f"🔧 [sub_server] Ошибка чтения user_configs: {e}", exc_info=True)

    # Шаг 2: Пытаемся получить актуальные данные с сервера
    expiry_text = None
    server_data_fetched = False  # Флаг: удалось ли получить данные с сервера

    if server_data:
        try:
            logger.info(f"📡 [sub_server] Запрашиваем expiryTime у сервера {server_id} для client_id={client_id}, email={email}")
            expiry_time = await sub_client(client_id, email, server_data)

            if expiry_time is not None and expiry_time > 0:
                expiry_dt = dt.fromtimestamp(expiry_time / 1000)
                now = dt.now().date()
                days_left = (expiry_dt.date() - now).days
                server_data_fetched = True  # Данные успешно получены

                # Обновляем days_left в БД
                try:
                    async with aiosqlite.connect("users.db") as conn:
                        await conn.execute(
                            "UPDATE user_configs SET days_left = ? WHERE email = ?",
                            (days_left, email)
                        )
                        await conn.commit()
                    logger.info(f"✅ [sub_server] Успешно обновлено days_left={days_left} для {email} в user_configs")
                except Exception as e:
                    logger.error(f"💾 [sub_server] Ошибка обновления days_left в БД: {e}", exc_info=True)

                # Формируем статус
                if days_left > 0:
                    expiry_text = f"📅 <b>Подписка действует до</b>: {expiry_dt.strftime('%Y-%m-%d')} (осталось <b>{days_left}</b> дн.)"
                elif days_left == 0:
                    expiry_text = "🟡 <b>Сегодня заканчивается ваша подписка</b>"
                else:
                    expiry_text = "❌ <b>Ваша подписка закончилась</b>"

            elif expiry_time == 0 or expiry_time < 0:
                logger.info(f"ℹ️ [sub_server] Сервер вернул expiry_time={expiry_time} — требуется активация")
                expiry_text = "✅ Активируйте конфигурацию в приложении."
                days_left = -1
                server_data_fetched = True  # Технически данные получены

        except Exception as e:
            logger.error(f"📡 [sub_server] Ошибка при запросе к серверу {server_id} для email={email}: {e}", exc_info=True)

    # Шаг 3: Решение — показывать ли кэш или ошибку
    if not server_data_fetched:
        logger.warning(f"🛑 [sub_server] Не удалось получить данные с сервера для email={email}. Показываем ошибку.")
        expiry_text = "❌ <b>Конфиг не найден на сервере. Обратитесь в поддержку</b>"
        can_extend = False  # ❌ Нельзя продлевать
    elif not expiry_text:
        logger.error(f"⚠️ [sub_server] Сервер ответил, но не удалось сформировать expiry_text для {email}")
        expiry_text = "⚠️ Статус подписки не определён"
        can_extend = False
    else:
        # Все остальные случаи — можно продлевать
        can_extend = True

    # Формируем result (как раньше)
    result = (
        f"👤 <b>Ваш айди</b>: {email}\n"
        f"{expiry_text}\n\n"
        f"🔑 <b>Ваш ключ</b>:\n\n<pre><code>{config}</code></pre>\n"
        f"*нажмите, чтобы скопировать☝️\n\n"
        f"🚨 <b>Тех поддержка</b>: @moy_help\n\n"
        f"<b>Инструкция для каждого устройства по кнопке ниже</b> 👇"
    )

    logger.info(f"✅ [sub_server] Ответ сформирован: can_extend={can_extend}, expiry_text='{expiry_text}'")
    return result, can_extend  # ⬅️ Возвращаем текст и флаг


async def sub_client(client_id, email, server_data):
    logger.info(f"🔐 [sub_client] Авторизация на сервере {server_data['name']} для получения данных клиента {email}")
    LOGIN_DATA = {
        "username": server_data["username"],
        "password": server_data["password"],
    }
    async with ClientSession(connector=TCPConnector(limit=100)) as session:
        try:
            login_response = await session.post(server_data["login_url"], json=LOGIN_DATA)
            if login_response.status != 200:
                text = await login_response.text()
                logger.error(f"🔐 [sub_client] Ошибка входа на сервер {server_data['name']}: {text}")
                return None
            logger.info(f"✅ [sub_client] Успешный вход на сервер {server_data['name']}")

            all_inbound_ids = server_data.get("inbound_ids", [])
            logger.info(f"📡 [sub_client] Запрашиваем данные из {len(all_inbound_ids)} inbounds: {all_inbound_ids}")

            tasks = [
                fetch_inbound_data(session, inbound_id, email, server_data)
                for inbound_id in all_inbound_ids
            ]
            results = await asyncio.gather(*tasks)
            result = next((r for r in results if r is not None), None)

            if result is not None:
                logger.info(f"✅ [sub_client] Найден expiryTime={result} для email={email}")
            else:
                logger.warning(f"🔍 [sub_client] Подписка не найдена для email={email} ни в одном из inbounds")

            return result
        except Exception as e:
            logger.error(f"🔐 [sub_client] Исключение при работе с сервером {server_data['name']}: {e}", exc_info=True)
            return None


async def fetch_inbound_data(session, inbound_id, email, server_data):
    """
    Возвращает timestamp окончания подписки (expiryTime) для клиента или None, если не найден.
    """
    logger.debug(f"📥 [fetch_inbound_data] Запрос данных для inbound_id={inbound_id}, email={email}")
    inbound_url = f"{server_data['config_client_url']}/{inbound_id}"
    try:
        inbound_response = await session.get(inbound_url, headers={'Accept': 'application/json'})
        if inbound_response.status != 200:
            text = await inbound_response.text()
            logger.error(f"❌ [fetch_inbound_data] Ошибка получения inbound {inbound_id}: статус {inbound_response.status}, {text}")
            return None

        inbound_data = await inbound_response.json()
        if inbound_data.get('obj') is None:
            logger.error(f"❌ [fetch_inbound_data] Поле 'obj' отсутствует в ответе для inbound_id={inbound_id}")
            return None

        clients = json.loads(inbound_data['obj']['settings']).get('clients', [])
        logger.debug(f"👥 [fetch_inbound_data] Найдено {len(clients)} клиентов в inbound_id={inbound_id}")

        client = next((client for client in clients if client['email'] == email), None)
        if not client:
            logger.info(f"🙈 [fetch_inbound_data] Клиент с email={email} не найден в inbound_id={inbound_id}")
            return None

        expiry_time = int(client['expiryTime'])
        logger.info(f"🎯 [fetch_inbound_data] Найден клиент: expiryTime={expiry_time} для email={email}")
        return expiry_time

    except Exception as e:
        logger.error(f"⚠️ [fetch_inbound_data] Ошибка при обработке inbound_id={inbound_id}: {e}", exc_info=True)
        return None


@router.callback_query(lambda c: c.data.startswith('extend_subscription_'))
async def process_extension(callback_query: types.CallbackQuery, state: FSMContext):
    email = callback_query.data.split("_", 2)[-1]
    await state.update_data(selected_email=email)
    telegram_id = callback_query.from_user.id

    # Получаем текст и флаг can_extend
    message_text, can_extend = await from_upd_sub(email)

    keyboard = InlineKeyboardBuilder()

    # Проверяем, можно ли продлевать
    free_days = 0
    is_free_extension_enabled = ENABLE_FREE_UPD.lower() == "true"
    if can_extend and is_free_extension_enabled:
        free_days = Database(USERSDATABASE).get_free_days_by_telegram_id(telegram_id)
        if free_days > 0:
            keyboard.add(InlineKeyboardButton(text="Продлить бесплатно", callback_data=f"extend_free_{email}"))

    if can_extend:
        keyboard.add(InlineKeyboardButton(text="Купить подписку", callback_data=f"extend_paid_{email}"))

    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu"))
    keyboard.adjust(1)

    # Подготовка сообщения
    if not can_extend:
        final_text = (
            f"{message_text.split('👤')[0].strip()}\n\n"
            "❌ <b>Продление недоступно</b>, так как конфиг не найден на сервере.\n"
            "Обратитесь в поддержку: @moy_help"
        )
    else:
        if free_days > 0 and is_free_extension_enabled:
            final_text = f"🎉 У вас есть <b>{int(free_days)} бесплатных дней</b>! Вы можете продлить подписку бесплатно."
        else:
            final_text = "Вы можете выбрать один из платных вариантов продления подписки."

    try:
        sent_message = await callback_query.message.edit_text(
            final_text,
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
        await state.update_data(sent_message_id=sent_message.message_id)
    except Exception as e:
        logger.error(f"❌ [process_extension] Ошибка при редактировании сообщения: {e}", exc_info=True)

    await callback_query.answer()


@router.callback_query(lambda c: c.data.startswith('extend_free_'))
async def process_free(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает бесплатное продление подписки, если у пользователя есть доступные дни.
    """    
    email = callback_query.data.split("_", 2)[-1]
    await state.update_data(selected_email=email)

    telegram_id = callback_query.from_user.id
    await state.update_data(selected_email=email)

    db = Database(USERSDATABASE)
    free_days = db.get_free_days_by_telegram_id(telegram_id)
    logger.info(f"Количество бесплатных дней для {telegram_id}: {free_days}")
    payment_methods_keyboard = InlineKeyboardBuilder()
    payment_methods_keyboard.add(InlineKeyboardButton(
            text=BUTTON_TEXTS["previous"], callback_data="main_menu"
        ))
    update_response = await update_client_subscription(telegram_id, email, free_days)
    if free_days > 0:
        new_free_days = free_days - free_days
        db.update_free_days_by_telegram_id(telegram_id, new_free_days)
        logger.info(f"Обновлено количество бесплатных дней для {telegram_id}: {new_free_days}")

    if free_days > 0:
        message_text = f"🎉 Ваши бесплатные дни использованы!\nПодписка на <b>{email}</b> была успешно продлена на <b>{int(free_days)}</b> дня(ей)."
    else:
        message_text = f"🔔 Подписка для клиента с email <b>{email}</b> была успешно продлена. Спасибо за использование наших услуг!"
    try:
        await callback_query.message.edit_text(
            message_text,
            reply_markup=payment_methods_keyboard.adjust(1).as_markup(),
            parse_mode="HTML"
        )
        logger.info(f"Подписка для клиента с email {email} была продлена на {free_days} дней.")
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
    
    await callback_query.answer()


@router.callback_query(lambda c: c.data.startswith('extend_paid_'))
async def process_paid(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Показывает пользователю варианты платного продления подписки на разные сроки.
    """
    email = callback_query.data.split("_", 2)[-1]
    await state.update_data(selected_email=email)

    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["one_m"], callback_data=f"extend_31_{email}"),
        InlineKeyboardButton(text=BUTTON_TEXTS["three_m"], callback_data=f"extend_93_{email}"),
        InlineKeyboardButton(text=BUTTON_TEXTS["twelve_m"], callback_data=f"extend_365_{email}"),
        InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu")
    ).adjust(2)

    try:
        sent_message = await callback_query.message.edit_text(
            f"На сколько месяцев вы хотите продлить подписку для {email}?",
            reply_markup=keyboard.as_markup()
        )
        await state.update_data(sent_message_id=sent_message.message_id)
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
    
    await callback_query.answer()


@router.callback_query(lambda c: c.data.startswith('extend_'))
async def process_month_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор пользователя по продолжительности продления подписки.
    - Извлекает выбранное количество месяцев для продления.
    - Сохраняет данные о выбранной продолжительности и логине в состоянии.
    - Отправляет сообщение с запросом ввести email или предлагает продолжить без email.
    """
    data = callback_query.data.split('_')
    if len(data) != 3 or not data[1].isdigit():
        await callback_query.answer("Некорректный формат данных. Попробуйте ещё раз.", show_alert=True)
        return

    months = int(data[1])
    name = data[2]
    logger.info(f"DEBUG: Выбрано {months} дня(ей) для {name}")

    # Здесь установим цену в зависимости от выбранного тарифа
    if months == 31:
        price = "80.00"  # Цена для 1 месяца
    elif months == 93:
        price = "200.00"  # Цена для 3 месяцев
    elif months == 365:
        price = "750.00"  # Цена для 12 месяцев
    else:
        price = "80.00"  # По умолчанию

    # Сохраняем цену в состоянии
    await state.update_data(selected_months=months)
    await state.update_data(name=name)
    await state.update_data(email="default@mail.ru")
    await state.update_data(price=price)  # Добавляем цену в state
    await callback_query.answer()

    cancel_keyboard = InlineKeyboardBuilder()
    cancel_keyboard.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["without_mail"], callback_data="continue_without_email"),
        InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel")
    )

    state_data = await state.get_data()

    # Сразу идём к оплате
    await process_yookassa(callback_query, state)
    return

    

@router.callback_query(lambda c: c.data == "continue_without_email", UpdClient.WaitingForEmail)
@router.message(UpdClient.WaitingForEmail)
async def handle_email_or_continue(callback: types.CallbackQuery | types.Message, state: FSMContext):
    #await state.set_state(UpdClient.WaitingForEmail)
    email = None
    user_id = None
    name = (await state.get_data()).get('selected_email')

    if isinstance(callback, types.CallbackQuery):
        email = EMAIL
        user_id = callback.from_user.id
        chat_id = user_id
        sent_message_id = (await state.get_data()).get('sent_message_id')
    elif isinstance(callback, types.Message):
        email = callback.text

        if not is_valid_email(email):
            invalid_email_msg = await callback.answer("Пожалуйста, введите корректный email.")
            await callback.delete()
            await asyncio.sleep(2)
            await invalid_email_msg.delete()
            return

        await callback.delete()
        user_id = callback.from_user.id
        chat_id = user_id
        sent_message_id = (await state.get_data()).get('sent_message_id')

    await state.update_data(email=email)
    await state.update_data(name=name)

    # Создаём клавиатуру с одной кнопкой "Юкасса" и кнопкой "Назад"
    payment_methods_keyboard = InlineKeyboardBuilder()
    payment_methods_keyboard.add(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["yokassa"],
            callback_data="payment_method_yookassa"
        )
    )
    payment_methods_keyboard.add(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["previous"],
            callback_data="main_menu"
        )
    )

    payment_method_text = (
        "⚙️ Выберите способ оплаты для продления подписки:\n\n"
        "💳 <b>Юкасса:</b> Оплата банковскими картами и электронными кошельками."
    )

    if sent_message_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message_id,
                text=payment_method_text,
                parse_mode='HTML',
                reply_markup=payment_methods_keyboard.adjust(1).as_markup()
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=payment_method_text,
                parse_mode='HTML',
                reply_markup=payment_methods_keyboard.adjust(1).as_markup()
            )
            await state.update_data(sent_message_id=sent_message.message_id)
    else:
        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=payment_method_text,
            parse_mode='HTML',
            reply_markup=payment_methods_keyboard.adjust(1).as_markup()
        )
        await state.update_data(sent_message_id=sent_message.message_id)

    await state.set_state(UpdClient.WaitingForPaymentMethod)

@router.callback_query(lambda c: c.data == "payment_method_yookassa")
async def process_yookassa(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    chat_id = callback.from_user.id
    email = data.get("email")
    name = data.get("name")
    expiry_time = data.get("expiry_time")  # убедись, что это значение было установлено ранее
    amount = data.get("price") or "80.00"  # Получаем цену из state или задаем дефолтную

    try:
        payment_url, payment_id = create_payment_yookassa(amount, chat_id, name, expiry_time, email)

        # Сохраняем payment_id в state или БД, если потом нужно будет проверять статус
        await state.update_data(payment_id=payment_id)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)
            ]]
        )

        await bot.send_message(
            chat_id=chat_id,
            text="Перейдите по ссылке ниже для оплаты подписки:",
            reply_markup=keyboard
        )

        await state.set_state(UpdClient.WaitingForPaymentMethod)
        await state.set_state(UpdClient.WaitingForPayment)
        asyncio.create_task(start_payment_status_update(callback, state, payment_id, "yookassa"))

    except Exception as e:
        import traceback
        error_text = f"❗ Ошибка при создании платежа:\n{str(e)}\n\n{traceback.format_exc()}"
        logger.error(error_text)
        await bot.send_message(chat_id=chat_id, text=error_text[:4000])  # Ограничим до 4000 символов




@router.callback_query(lambda c: c.data.startswith("payment_method_"))
async def handle_payment_method_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор способа оплаты от клиента.
    Устанавливает состояние ожидания выбора способа оплаты и генерирует соответствующую ссылку для оплаты.
    """
    await state.set_state(UpdClient.WaitingForPaymentMethod)

    payment_method = callback_query.data.split("_")[2]
    await state.update_data(payment_method=payment_method)
    data = await state.get_data()
    name = data.get("name")
    email = data.get("email")
    user_id = callback_query.from_user.id
    months = data.get("selected_months", 1)
    expiry_time = {
        31: ONE_M,
        93: THREE_M,
        185: SIX_M,
        365: ONE_YEAR,
    }.get(months, ONE_M)
    conn_users = sqlite3.connect(USERSDATABASE)
    cursor_users = conn_users.cursor()

    cursor_users.execute("""
        SELECT promo_code
        FROM users
        WHERE telegram_id = ?
    """, (user_id,))
    user_promo_code = cursor_users.fetchone()

    if user_promo_code and user_promo_code[0]:
        user_promo_code = user_promo_code[0]
    else:
        user_promo_code = None
        
    price_info = get_price_with_referral_info(expiry_time, user_id, user_promo_code)
    final_price = int(price_info[0])
    try:
        if payment_method == "yookassa":
            payment_url, payment_id = create_paymentupdate(final_price, user_id, email)
        elif payment_method == "yoomoney":
            label = str(uuid.uuid4()) 
            payment_url, payment_id = create_yoomoney_invoice(final_price, YOOMONEY_CARD, label)
            logger.info(f"DEBUG: юмани - {payment_url}, payment_id - {payment_id}")
        elif payment_method == "robokassa":
            payment_url, payment_id = create_payment_robokassa(final_price, user_id, name, expiry_time, email)
        elif payment_method == "cryptobot":
            payment_url, payment_id = await create_payment_cryptobot(final_price, user_id)
        elif payment_method == "cloudpay":
            invoice_id = str(uuid4())
            payment_url, payment_id = await create_cloudpayments_invoice(final_price, user_id, invoice_id)
        elif payment_method == "tgpay":
            sent_message = await bot.edit_message_text(
                chat_id=callback_query.from_user.id,
                message_id=callback_query.message.message_id,
                text="🔄 Создаем платеж...",
                parse_mode='HTML'
            )
            await asyncio.sleep(2)
            await bot.delete_message(chat_id=callback_query.from_user.id, message_id=sent_message.message_id)

            await create_payment_tgpay(final_price, user_id, name, expiry_time, payment_type="subscription_renewal", pay_currency="tgpay")
            return
        elif payment_method == "star":
            sent_message = await bot.edit_message_text(
                chat_id=callback_query.from_user.id,
                message_id=callback_query.message.message_id,
                text="🔄 Создаем платеж...",
                parse_mode='HTML'
            )
            await asyncio.sleep(2)
            await bot.delete_message(chat_id=callback_query.from_user.id, message_id=sent_message.message_id)

            await create_payment_tgpay(final_price, user_id, name, expiry_time, payment_type="subscription_renewal", pay_currency="xtr")
            return
        else:
            await callback_query.answer("❌ Неизвестный способ оплаты.")
            return

        keyboard = InlineKeyboardBuilder()

        keyboard.add(
            InlineKeyboardButton(text=BUTTON_TEXTS["pay"], url=payment_url),
            InlineKeyboardButton(text=BUTTON_TEXTS["check_pay"], callback_data=f"find_payment:{payment_id}:{payment_method}"),
            InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="upd_cancel")
        )
        payment_text = (
            f"💳 <b>Продление подписки</b>, количество дней: <b>{months}</b>\n\n"
            f"Стоимость со скидкой: <b>{final_price} ₽</b>\n\n"
            "⚠️ <i>Если передумали или выбрали не то, не оплачивайте, а просто нажмите 'Отмена'.</i>\n\n"
        )
        if email != EMAIL:
            payment_text += f"📧 Чек будет отправлен на указанный адрес электронной почты: {email}"

        sent_message_id = data.get('sent_message_id')
        if sent_message_id:
            await bot.edit_message_text(
                chat_id=callback_query.from_user.id,
                message_id=sent_message_id,
                text=payment_text,
                parse_mode='HTML',
                reply_markup=keyboard.adjust(2).as_markup()
            )
        else:
            sent_message = await bot.send_message(
                chat_id=callback_query.from_user.id,
                text=payment_text,
                parse_mode='HTML',
                reply_markup=keyboard.adjust(2).as_markup()
            )
            await state.update_data(sent_message_id=sent_message.message_id, user_promo_code=user_promo_code)
        await state.update_data(payment_id=payment_id, final_price=final_price)
        await state.set_state(UpdClient.WaitingForPayment)
        asyncio.create_task(start_payment_status_update(callback_query, state, payment_id, payment_method))
        
    except Exception as e:
        logger.error(f"Ошибка при обработке платежа: {e}")
        await callback_query.answer("❌ Произошла ошибка при создании платежа. Попробуйте позже.")


async def check_payment_status_common(payment_id: str, payment_method: str) -> bool:
    """
    Проверяет статус платежа по различным методам.
    """
    try:
        if payment_method == "yookassa":
            return await check_payment_yookassa(payment_id)
        elif payment_method == "yoomoney":
            return await check_yoomoney_payment_status(payment_id)
        elif payment_method == "robokassa":
            password2 = PASS2
            result = await check_payment_robokassa(payment_id, password2)
            return result == "100"
        elif payment_method == "cryptobot":
            return await check_payment_cryptobot(payment_id)
        elif payment_method == "cloudpay":
            return await check_payment_cloud(payment_id)
        else:
            logger.error(f"Неизвестный метод оплаты: {payment_method}")
            return False
    except Exception as e:
        logger.error(f"Ошибка при проверке платежа ({payment_method}): {e}")
        return False
    

async def finalize_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает завершение подписки и обновление данных клиента в базе.
    """
    try:
        data = await state.get_data()
        name = data.get("name")
        final_price = data.get("price")
        months = data.get("selected_months")
        user_promo_code = data.get("user_promo_code")
        telegram_id = callback_query.from_user.id

        # Обновление подписки
        await update_client_subscription(telegram_id, name, months)
        await handle_database_operations(telegram_id, name, months)
        await log_promo_code_usage(telegram_id, user_promo_code)
        await update_sum_my(telegram_id, float(final_price))
        await update_sum_ref(telegram_id, final_price)
        await add_free_days(telegram_id, FREE_DAYS)

        # Отправка первого сообщения о продлении подписки
        await callback_query.message.edit_text(
            text=f"✅ Подписка продлена на {months} день(ней)!",
            parse_mode='HTML',
            reply_markup=get_back_button()  # Кнопка "назад"
        )

        # Убираем старую кнопку "перейти к оплате" и все связанные с ней элементы
        #await callback_query.message.edit_message_reply_markup(reply_markup=None)  # Удаляем все кнопки

        # После этого снова устанавливаем нужную кнопку
        #await callback_query.message.edit_message_reply_markup(reply_markup=get_back_button())  # Только кнопка "назад"
        #await callback_query.message.answer("✅ Подписка успешно продлена!")

        # Очистка состояния FSM
        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка при обновлении подписки: {e}")
        await callback_query.answer("Произошла ошибка при обновлении подписки. Пожалуйста, попробуйте позже.")


        
renewal_tasks = {}

async def start_payment_status_update(callback_query: types.CallbackQuery, state: FSMContext, payment_id: str, payment_method: str):
    """
    Начинает асинхронную проверку статуса платежа, периодически проверяя завершение оплаты.

    Эта функция будет выполняться в фоновом режиме, пытаясь проверить статус платежа через
    выбранный метод оплаты (Юкасса, Робокасса и т.д.) и обновлять статус в случае успешной
    оплаты или по истечении максимального времени ожидания.
    """
    task_id = f"{callback_query.from_user.id}_{payment_id}"
    try:
        attempts = 0
        renewal_tasks[task_id] = asyncio.current_task()

        await asyncio.sleep(FIRST_CHECK_DELAY)

        while attempts < MAX_ATTEMPTS:
            payment_check = await check_payment_status_common(payment_id, payment_method)
            if payment_check:
                await finalize_subscription(callback_query, state)
                return

            attempts += 1
            logger.info(f"Попытка {attempts}: Платеж не завершен, ждем {SUBSEQUENT_CHECK_INTERVAL} секунд")
            await asyncio.sleep(SUBSEQUENT_CHECK_INTERVAL)

        await callback_query.answer("❌ Платеж не был завершен в установленное время.")
    except asyncio.CancelledError:
        logger.info(f"Задача {task_id} была отменена.")
    except Exception as e:
        logger.error(f"Ошибка при автоматической проверке платежа: {e}")
    finally:
        renewal_tasks.pop(task_id, None)

@router.callback_query(lambda c: c.data.startswith("find_payment:"), UpdClient.WaitingForPayment)
async def check_payment_status(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос клиента для проверки статуса оплаты по идентификатору платежа.
    """
    try:
        payment_data = callback_query.data.split(':')
        if len(payment_data) < 3:
            await callback_query.answer("Некорректные данные. Пожалуйста, попробуйте снова.")
            return

        payment_id = payment_data[1]
        payment_method = payment_data[2]

        payment_check = await check_payment_status_common(payment_id, payment_method)
        if not payment_check:
            await callback_query.answer("❌ Платеж не был завершен. Пожалуйста, проверьте и попробуйте снова.")
            return

        await finalize_subscription(callback_query, state)

        task_id = f"{callback_query.from_user.id}_{payment_id}"
        if task_id in renewal_tasks:
            task = renewal_tasks.pop(task_id)
            task.cancel()
            logger.info(f"Задача {task_id} была успешно отменена вручную.")
    except Exception as e:
        logger.error(f"Ошибка при проверке платежа: {e}")
        await callback_query.answer("Произошла ошибка при проверке платежа. Пожалуйста, попробуйте позже.")

async def create_update_data(client_id, email, new_expiry_time, client, INBOUND_ID, UPDATE_CLIENT):
    """
    Создает данные для обновления подписки клиента на сервере.
    """
    return {
        "id": INBOUND_ID,
        "settings": json.dumps({
            "clients": [{
                "id": f"{client_id}",
                "email": email,
                "expiryTime": new_expiry_time,
                "enable": client.get('enable', True),
                "tgId": client.get('tgId', ''),
                "limitIp": client.get('limitIp', 3),
                "subId": client.get('subId', ''),
                "flow": 'xtls-rprx-vision',
                "reset": 0
            }]
        }, indent=4)
    }

async def update_client_subscription(telegram_id, email, days):
    """
    Обновляет подписку клиента на всех серверах, используя дни.
    """
    server_ids = await get_server_id(SERVEDATABASE)
    server_ids = [sid for sid in server_ids if sid]  # убираем None, 0, ''
    full_response = []
    for server_id in server_ids:
        server_data = await get_server_data(server_id)
        if not server_data:
            continue
        LOGIN_URL = server_data.get('login_url')
        CONFIG_CLIENT_URL = server_data.get('config_client_url')
        INBOUND_IDS = server_data.get('inbound_ids')
        UPDATE_CLIENT = server_data.get('update_url')
        if not LOGIN_URL:
            continue
        email = email
        session = requests.Session()
        login_response = session.post(LOGIN_URL, json={'username': server_data['username'], 'password': server_data['password']})
        if login_response.status_code != 200:
            continue
        for INBOUND_ID in INBOUND_IDS:
            try:
                inbound_url = f"{CONFIG_CLIENT_URL}/{INBOUND_ID}"
                inbound_response = session.get(inbound_url, headers={'Accept': 'application/json'})
                if inbound_response.status_code != 200:
                    continue
                inbound_data = inbound_response.json().get('obj')
                if inbound_data is None:
                    continue

                settings = json.loads(inbound_data['settings'])
                client = next((client for client in settings['clients'] if client['email'] == email), None)
                if not client:
                    continue
                client_id = client['id']
                client_expiry_time = client.get('expiryTime', 0)
                current_time_ms = int(time.time() * 1000)
                
                if client_expiry_time < current_time_ms:
                    # Если срок подписки истек, то добавляем дни к текущему времени
                    new_expiry_time = current_time_ms + (days * 24 * 60 * 60 * 1000)  # дни в миллисекундах
                else:
                    # Если срок подписки не истек, добавляем дни к текущему времени подписки
                    new_expiry_time = int(client_expiry_time) + (days * 24 * 60 * 60 * 1000)  # дни в миллисекундах
                
                logger.info(f"Найден клиент с email {email} на сервере {server_id}. Срок действия подписки: {client_expiry_time}.")
                logger.info(f"Обновляем подписку для клиента с email {email} на сервере {server_id}, новый срок окончания: {new_expiry_time}.")
                
                update_data = await create_update_data(client_id, email, new_expiry_time, client, INBOUND_ID, UPDATE_CLIENT)
                headers = {'Accept': 'application/json'}
                response = session.post(f"{UPDATE_CLIENT}/{client_id}", json=update_data, headers=headers)
                logger.info(f"Данные, отправляемые в POST-запросе: {json.dumps(update_data, indent=2)}")
                
                if response.status_code == 200:
                    full_response.append(f"Подписка для клиента с email {email} успешно продлена на сервере {server_id}.")
                    await send_telegram_message(telegram_id, "✅ Ваша подписка успешно обновлена.")
		    
		    # Отправка уведомления в группу
                    user = await bot.get_chat(telegram_id)
                    full_name = user.full_name or f"Пользователь {telegram_id}"
                    user_link = f"<a href='tg://user?id={telegram_id}'>{full_name}</a>"
                    expiry_time_description = time.strftime('%d.%m.%Y %H:%M', time.localtime(new_expiry_time / 1000))  # читаемый срок действия
                    userdata = f"ID: {telegram_id}"
                    email_raw = email

                    await bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text=(
                            f"📩 <b>Пользователь</b> {user_link} продлил подписку до <b>{expiry_time_description}</b>\n"
                            f"👤 {userdata}\n"
                            f"📧 Email: <code>{email_raw}</code>"
                        ),
                        parse_mode=ParseMode.HTML
                    )
                else:
                    full_response.append(f"Ошибка продления подписки для клиента с email {email} на сервере {server_id}. Ответ: {response.text}")
            except Exception as e:
                logger.error(f"Ошибка при обработке сервера {server_id}: {e}")
                continue
    if full_response:
        return "\n".join(full_response)
    else:
        return "❌ Ошибка продления подписки для клиента. Проверьте логин, данные или сервер."

# Функция отправки сообщения
async def send_telegram_message(telegram_id, message):
    try:
        await bot.send_message(chat_id=telegram_id, text=message)
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения в Telegram: {e}")

@router.callback_query(lambda c: c.data == "upd_cancel")
async def handle_cancel_payment(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос клиента на отмену текущего платежа.
    """
    try:
        data = await state.get_data()
        sent_message_id = data.get('sent_message_id')
        payment_id = data.get('payment_id')
        payment_method = data.get('payment_method')

        if not payment_id:
            await callback_query.answer("❌ Не удалось найти платежный процесс. Пожалуйста, попробуйте снова.")
            return

        is_payment_completed = await check_payment_status_common(payment_id, payment_method)
        if is_payment_completed:
            await callback_query.answer("❌ Платеж завершен. Отмена невозможна, нажмите кнопку, Проверить оплату")
            return

        task_id = f"{callback_query.from_user.id}_{payment_id}"
        if task_id in renewal_tasks:
            task = renewal_tasks.pop(task_id)
            task.cancel()
            logger.info(f"Задача {task_id} была успешно отменена вручную.")
            await callback_query.answer("❌ Оплата была отменена.")
        else:
            await callback_query.answer("❌ Задача не найдена. Возможно, платеж уже завершен.")

        if sent_message_id:
            await bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=sent_message_id,
                text="❌ Действие отменено.",
                reply_markup=get_main_menu(callback_query)
            )
        else:
            await bot.send_message(
                chat_id=callback_query.message.chat.id,
                text="Нет активной покупки. Выберите опцию:",
                reply_markup=get_main_menu(callback_query)
            )

        await state.clear()
        await callback_query.answer()

    except Exception as e:
        logger.error(f"Ошибка при отмене платежа: {e}")
        await bot.send_message(
            chat_id=callback_query.message.chat.id,
            text="Не удалось отменить покупку. Попробуйте снова.",
            reply_markup=get_main_menu(callback_query)
        )


from aiogram import Dispatcher, types
from aiogram.types import Message
from aiogram.filters import Command
dp = Dispatcher()
REFERRAL_CHAT_ID = -1003045150256
@router.message(Command("test_chats"))
async def test_chats(message: Message):
    try:
        await bot.send_message(GROUP_CHAT_ID, "✅ Тест: бот видит GROUP_CHAT_ID")
        await message.answer("✅ Сообщение в GROUP_CHAT_ID отправлено")
    except Exception as e:
        await message.answer(f"❌ Ошибка в GROUP_CHAT_ID: {e}")

    try:
        await bot.send_message(REFERRAL_CHAT_ID, "✅ Тест: бот видит REFERRAL_CHAT_ID")
        await message.answer("✅ Сообщение в REFERRAL_CHAT_ID отправлено")
    except Exception as e:
        await message.answer(f"❌ Ошибка в REFERRAL_CHAT_ID: {e}")



# ID пользователя, по которому проверяем рефералов
TARGET_USER_ID = 1311997119
DB_PATH = "users.db"  # ← Укажи правильный путь к твоему .db файлу

@router.message(Command("ref_freez"))
async def cmd_ref_freez(message: types.Message):
    # Проверяем, что команда вызвана в личных сообщениях (не в группе)
    if message.chat.type != "private":
        await message.answer("❗ Эта команда доступна только в личных сообщениях с ботом.")
        return

    try:
        # Подключаемся к базе данных
        async with aiosqlite.connect(DB_PATH) as db:
            # Запрос: количество рефералов
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE referred_by = ?", (TARGET_USER_ID,)
            ) as cursor:
                count_row = await cursor.fetchone()
                count_referrals = count_row[0] if count_row else 0

            # Запрос: сумма sum_my
            async with db.execute(
                "SELECT COALESCE(SUM(sum_my), 0) FROM users WHERE referred_by = ?", (TARGET_USER_ID,)
            ) as cursor:
                sum_row = await cursor.fetchone()
                total_sum = sum_row[0] if sum_row else 0.0

        # Формируем и отправляем ответ в личные сообщения
        await message.answer(
            f"🔐 <b>Реферальная статистика для ID {TARGET_USER_ID}:</b>\n\n"
            f"👥 Всего рефералов: <b>{count_referrals}</b>\n"
            f"💰 Сумма (sum_my): <b>{total_sum:.2f}</b>",
            parse_mode="HTML"
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка при работе с базой данных:\n{e}")



@router.callback_query(lambda c: c.data.startswith('trial_seven_'))
async def process_trial_seven(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        logger.info(f"🔧 [trial_seven] Кнопка нажата: {callback_query.data}")
        email = callback_query.data.split("_", 2)[-1]
        telegram_id = callback_query.from_user.id

        db = Database(USERSDATABASE)

        if db.has_used_trial_seven(telegram_id):
            await callback_query.answer("🎁 Вы уже использовали пробный период.", show_alert=True)
            return

        # Получаем user_id из user_emails
        server_ids = await db.get_server_ids_by_email(email)
        if not server_ids:
            await callback_query.answer("❌ Подписка не найдена.", show_alert=True)
            return

        # 🔥 Используем РАБОЧУЮ функцию
        result = await update_client_subscription(telegram_id, email, 7)

        # Проверяем, был ли успех
        if "успешно" in result or "success" in result or "Подписка для клиента" in result:
            # Обновляем days_left в user_configs
            async with aiosqlite.connect("users.db") as conn:
                await conn.execute(
                    "UPDATE user_configs SET days_left = COALESCE(days_left, 0) + 7 WHERE email = ?",
                    (email,)
                )
                await conn.commit()

            # Отмечаем использование
            db.mark_trial_seven_used(telegram_id)

            # Обновляем статус
            new_status = await from_upd_sub(email)

            try:
                await callback_query.message.edit_text(
                    f"🎉 <b>Вам начислено 7 дней подписки!</b>\n\n",
                    parse_mode="HTML",
                    reply_markup=callback_query.message.reply_markup
                )
            except Exception as e:
                logger.error(f"📝 Ошибка редактирования: {e}")
                await callback_query.message.answer(f"🎉 Подписка продлена!\n\n{new_status}", parse_mode="HTML")

            await callback_query.answer("✅ Подписка продлена на 7 дней!")
        else:
            logger.error(f"❌ Ошибка в update_client_subscription: {result}")
            await callback_query.answer("❌ Не удалось продлить подписку.", show_alert=True)

    except Exception as e:
        logger.error(f"💥 Ошибка в trial_seven: {e}", exc_info=True)
        await callback_query.answer("❌ Произошла ошибка.", show_alert=True)

async def extend_subscription_on_server(server_id: int, email: str, days: int):
    """
    Продлевает подписку, обновляя inbound через POST /panel/api/inbounds.
    Исправлено для работы с self-signed SSL и XUI-панелью.
    """
    logger.info(f"🚀 [EXTEND] Продление: server_id={server_id}, email={email}, days={days}")

    server_data = await get_server_data(server_id)
    if not server_data:
        logger.error(f"❌ [EXTEND] Не найдены данные сервера: {server_id}")
        return False

    # URLs
    LOGIN_URL = server_data["login_url"]
    CONFIG_CLIENT_URL = server_data["config_client_url"]  # .../get/{id}
    BASE_API_URL = CONFIG_CLIENT_URL.rstrip('/get')  # → .../panel/api/inbounds
    UPDATE_URL = BASE_API_URL  # POST на этот URL

    INBOUND_IDS = server_data.get("inbound_ids", [])
    USERNAME = server_data["username"]
    PASSWORD = server_data["password"]

    # Важно: без / в конце и без пробелов
    REFERER_URL = "https://3.vpnmojno.ru:48701/0LYlqkjIMRPFdSi/"

    # Заголовки — как в браузере
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": REFERER_URL
    }

    # 🔽 Ключевое исправление: отключаем проверку SSL (self-signed сертификат)
    connector = TCPConnector(limit=100, ssl=False)

    async with ClientSession(connector=connector) as session:
        try:
            # 🔐 1. Логин
            login_response = await session.post(
                LOGIN_URL,
                json={"username": USERNAME, "password": PASSWORD},
                headers=headers
            )
            logger.info(f"🔐 [EXTEND] Статус входа: {login_response.status}")

            if login_response.status != 200:
                error_text = await login_response.text()
                logger.error(f"🔴 Ошибка входа: {error_text}")
                return False

            logger.info("✅ Успешный вход")

            # 🔁 Перебираем inbounds
            for inbound_id in INBOUND_IDS:
                get_url = f"{CONFIG_CLIENT_URL}/{inbound_id}"
                logger.info(f"📥 Запрашиваем inbound {inbound_id}...")

                get_response = await session.get(get_url, headers=headers)
                logger.info(f"📡 Статус получения inbound: {get_response.status}")

                if get_response.status != 200:
                    error_text = await get_response.text()
                    logger.warning(f"⚠️ Ошибка получения inbound {inbound_id}: {error_text}")
                    continue

                try:
                    # Попытка распарсить JSON
                    inbound_data = await get_response.json()
                    obj = inbound_data.get("obj")
                    if not obj:
                        logger.warning(f"🟡 'obj' пустой в inbound {inbound_id}")
                        continue

                    settings = json.loads(obj["settings"])
                    clients = settings.get("clients", [])
                    target_client = next((c for c in clients if c["email"] == email), None)

                    if not target_client:
                        logger.info(f"🙈 Клиент с email={email} не найден в inbound {inbound_id}")
                        # Для отладки — покажем первые email'ы
                        sample_emails = [c.get("email") for c in clients[:3]]
                        logger.info(f"📋 Пример email'ов: {sample_emails}")
                        continue

                    logger.info(f"🎯 Клиент найден: {email}")

                    # 📅 Вычисляем новую дату
                    now_ms = int(dt.now().timestamp() * 1000)
                    current_expiry = target_client.get("expiryTime", 0)

                    if current_expiry <= now_ms:
                        new_expiry = now_ms + days * 24 * 3600 * 1000
                        logger.info(f"🆕 Подписка просрочена — новая дата: {dt.fromtimestamp(new_expiry / 1000)}")
                    else:
                        new_expiry = current_expiry + days * 24 * 3600 * 1000
                        logger.info(f"🆕 Продлеваем подписку: до {dt.fromtimestamp(new_expiry / 1000)}")

                    # 📤 Создаём тело запроса
                    update_data = await create_update_data(
                        client_id=target_client["id"],
                        email=email,
                        new_expiry_time=new_expiry,
                        client=target_client,
                        INBOUND_ID=inbound_id,
                        UPDATE_CLIENT=UPDATE_URL
                    )

                    logger.info(f"📤 Отправляем обновление на: {UPDATE_URL}")
                    logger.debug(f"📊 Данные для отправки: {update_data}")

                    # 🚀 Отправляем обновление
                    save_response = await session.post(UPDATE_URL, json=update_data, headers=headers)
                    logger.info(f"💾 Статус сохранения: {save_response.status}")

                    if save_response.status == 200:
                        try:
                            result = await save_response.json()
                            logger.info(f"✅ Успешный JSON-ответ: {result}")
                        except Exception:
                            text = await save_response.text()
                            logger.info(f"✅ Успешно (text): '{text.strip()}'")
                        return True
                    else:
                        error_text = await save_response.text()
                        logger.error(f"❌ Ошибка сохранения: {error_text}")

                except Exception as e:
                    logger.error(f"🔧 Ошибка при обработке inbound {inbound_id}: {e}", exc_info=True)
                    continue

            logger.warning(f"❌ Не удалось продлить подписку для {email}")
            return False

        except Exception as e:
            logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
            return False