import json
import random
import string
import uuid
from datetime import datetime as dt
import requests
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.enums.parse_mode import ParseMode
from bot import bot, dp
from client.menu import get_instructions_button
from handlers.config import get_server_data
from handlers.states import AddClient
from pay.prices import get_expiry_time_keyboard, total_gb_values
from pay.prices import get_expiry_time_description
from buttons.client import BUTTON_TEXTS
from db.db import get_server_ids_as_list, save_config_to_new_table
from dotenv import load_dotenv
import os
import aiohttp
from log import logger
from handlers.select_server import get_optimal_server
import aiosqlite
from aiogram.types import Message

load_dotenv()

AUTOHIDDIFY = os.getenv("AUTOHIDDIFY")
AUTOSTREI = os.getenv("AUTOSTREI")
LINUX = os.getenv("LINUX")
WINDOWS = os.getenv("WINDOWS")
MAC = os.getenv("MAC")
LOGIN = os.getenv("LOGIN")
SERVEDATABASE = os.getenv("SERVEDATABASE")

USERSDATABASE = os.getenv("USERSDATABASE")

def generate_login(telegram_id):
    """
    Генерация логина для клиента, используя его Telegram ID.
    Логин формируется из переменной LOGIN и использованиея последних 4 цифр ID пользователя и 3 случайных цифр.
    Пример: 3x-ui-1111333
    """
    id_suffix = str(telegram_id)[-4:]
    random_digits = ''.join(random.choices('0123456789', k=3))
    return f"{LOGIN}-{id_suffix}{random_digits}"


"""async def start_add_client(callback_query: types.CallbackQuery, state: FSMContext):
    
    Обработчик команды добавления клиента, который активируется при нажатии кнопки. 
    Сохраняет информацию о сессии и отображает клавиатуру для выбора страны.
    
    telegram_id = callback_query.from_user.id
    generated_name = generate_login(telegram_id)
    await state.update_data(
        name = generated_name,
        sent_message_id = callback_query.message.message_id
    )
    countries_keyboard = await generate_countries_keyboard(callback_query)
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text="🌍 Выберите страну:",
        reply_markup=countries_keyboard
    )
    await state.set_state(AddClient.WaitingForCountry)"""

async def start_add_client(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обработчик команды добавления клиента, который сразу выбирает первую страну по умолчанию
    и переходит к шагу выбора срока.
    """
    telegram_id = callback_query.from_user.id
    generated_name = generate_login(telegram_id)
    await state.update_data(
        name=generated_name,
        sent_message_id=callback_query.message.message_id
    )

    # Получаем первую доступную страну (сервер)
    server_ids = await get_server_ids_as_list(SERVEDATABASE)
    if not server_ids:
        await callback_query.answer("Нет доступных серверов 😔", show_alert=True)
        return

    first_server_id = server_ids[0]
    server_data = await get_server_data(first_server_id)
    country_name = server_data.get('name') if server_data else "🎲 Рандомная страна"

    # Сохраняем выбор в state
    await state.update_data(
        selected_country_id=first_server_id,
        selected_country_name=country_name
    )

    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text="<b>Теперь выберите срок подключения:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_expiry_time_keyboard(callback_query)
    )

    await state.set_state(AddClient.WaitingForExpiryTime)


async def generate_countries_keyboard(callback_query: types.CallbackQuery):
    """
    Генерация клавиатуры с кнопками для выбора страны.
    Отображает список доступных стран на основе серверов.
    """
    keyboard = InlineKeyboardBuilder()
    for server_id in await get_server_ids_as_list(SERVEDATABASE):
        server_data = await get_server_data(server_id)
        if server_data:
            country_name = server_data['name']
            keyboard.add(types.InlineKeyboardButton(text=country_name, callback_data=f"select_country_{server_id}"))
    keyboard.add(types.InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel"))
    return keyboard.adjust(1).as_markup()


@dp.callback_query(lambda c: c.data and c.data.startswith('select_country_'), AddClient.WaitingForCountry)
async def country_selection_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обработчик выбора страны. Сохраняет выбранную страну и предлагает выбрать срок подключения.
    """
    server_selection = callback_query.data.split("_")[-1]
    server_data = await get_server_data(server_selection)
    country_name = server_data.get('name') if server_data else "🎲 Рандомная страна"
    await state.update_data(
        selected_country_id = server_selection,
        selected_country_name = country_name
    )
    await callback_query.answer("Страна выбрана! Теперь выберите срок подключения.")
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text="✅ Выберите срок подключения:",
        reply_markup=get_expiry_time_keyboard(callback_query)
    )
    await state.set_state(AddClient.WaitingForExpiryTime)

async def add_client(name, expiry_time, inbound_ids, telegram_id, ADD_CLIENT_URL, LOGIN_URL, LOGIN_DATA):
    """
    Функция для добавления клиента на сервер. Включает процесс аутентификации и отправку данных клиента.
    Возвращает результат операции.
    """
    session_id = await login(LOGIN_URL, LOGIN_DATA)
    if session_id:
        if name and expiry_time:
            client_id = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
            add_client_result = await add_client_request(session_id, name, expiry_time, client_id, inbound_ids, ADD_CLIENT_URL, telegram_id)
            return add_client_result
        else:
            return "❌ Ошибка: имя или срок действия подписки не указаны."
    else:
        return "❌ Ошибка аутентификации."

async def add_client_request(session_id, name, expiry_time, client_id, inbound_ids, ADD_CLIENT_URL, telegram_id):
    """
    Функция для отправки запроса на добавление клиента на сервер. 
    Использует сессионный ID для аутентификации и данные для создания клиента.
    Возвращает результат операции.
    """
    logger.info(f"Начинаем добавление клиента с ID {client_id} на сервер с URL: {ADD_CLIENT_URL}")

    id_vless = random.choice(inbound_ids)
    sub_id = f"{LOGIN}-{uuid.uuid4().hex[:8]}"
    client_data = {
        "id": id_vless,
        "settings": json.dumps({
            "clients": [{
                "id": client_id,
                "alterId": 0,
                "email": name,
                "limitIp": 5,
                "totalGB": total_gb_values.get(int(expiry_time), 0),
                "expiryTime": expiry_time,
                "enable": True,
                "subId": sub_id,
                "tgId": telegram_id,
                "flow": "xtls-rprx-vision"
            }]
        })
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json", "Cookie": f"3x-ui={session_id}"}
    async with aiohttp.ClientSession() as session:
        try:
            response = await session.post(ADD_CLIENT_URL, headers=headers, json=client_data)
            if response.status == 200:
                return "✅ Оплата успешно подтверждена и подписка активирована. 🎆."
            else:
                return "❌ Произошла ошибка при добавлении клиента."
        except Exception as e:
            return "❌ Произошла ошибка при добавлении клиента."
        
async def login(LOGIN_URL, LOGIN_DATA):
    """
    Функция для аутентификации клиента через внешний сервис, используя данные для логина.
    Возвращает session_id в случае успешной аутентификации.
    """
    response = requests.post(LOGIN_URL, data=LOGIN_DATA)
    if response.status_code == 200:
        session_id = response.cookies.get("3x-ui")
        return session_id
    return None

async def generate_config_from_pay(telegram_id, email, state):
    """
    Генерация конфигурации для клиента на основе его данных. Возвращает конфигурации для разных устройств.
    """
    data = await state.get_data()
    LOGIN_URL = data.get('login_url')
    LOGIN_DATA = data.get('login_data')
    CONFIG_CLIENT_URL = data.get('config_client_url')
    INBOUND_IDS = data.get('inbound_ids')
    session = requests.Session()
    login_response = session.post(LOGIN_URL, json=LOGIN_DATA)
    if login_response.status_code != 200:
        return "", ""
    
    userdata_list, config_list, config_list2, config_list3 = [], [], [], []
    for INBOUND_ID in INBOUND_IDS:
        try:
            inbound_url = f"{CONFIG_CLIENT_URL}/{INBOUND_ID}"
            inbound_response = session.get(inbound_url, headers={'Accept': 'application/json'})
            if inbound_response.status_code != 200:
                continue
            inbound_data = inbound_response.json().get('obj')
            if not inbound_data:
                continue
            port = inbound_data['port']
            settings = json.loads(inbound_data['settings'])
            stream_settings = json.loads(inbound_data['streamSettings'])
            client = next((client for client in settings['clients'] if client['email'].lower() == email), None)
            if not client:
                continue
            client_id = client['id']
            sub_id = client.get('subId', None)
            network = stream_settings['network']
            security = stream_settings['security']
            public_key = stream_settings['realitySettings']['settings']['publicKey']
            fingerprint = stream_settings['realitySettings']['settings']['fingerprint']
            sni = stream_settings['realitySettings']['serverNames'][0]
            short_id = stream_settings['realitySettings']['shortIds'][0]
            spider_x_encoded = stream_settings['realitySettings']['settings']['spiderX'].replace('/', '%2F')

            config_url = f"{data['sub_url']}{sub_id}"
            config_json = f"{data['json_sub']}{sub_id}"
            vless_config = f"vless://{client_id}@{data['server_ip']}:{port}?type={network}&security={security}&pbk={public_key}&fp={fingerprint}&sni={sni}&sid={short_id}&spx={spider_x_encoded}F&flow=xtls-rprx-vision#{email}\n"
            expiry_time_ms = client['expiryTime']
            expiry_text = "Новая подписка." if int(expiry_time_ms) < 0 else dt.fromtimestamp(expiry_time_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
            userdata_list.append(f"{expiry_text}\n")
            config_list.append(config_url)
            config_list2.append(config_json)
            config_list3.append(vless_config)
        except Exception:
            continue

    return "\n".join(userdata_list), "\n\n".join(config_list), "\n\n".join(config_list2), "\n\n".join(config_list3)

GROUP_CHAT_ID = -4924146649
REFERRAL_CHAT_ID = -1003045150256

async def send_config_from_state(message: Message, state: FSMContext, telegram_id=None, email=None, edit=False, tickets_message=None):
    """
    Отправляет конфиг пользователю и уведомления в группы.
    Если referrer_code == 'eb1a1788' → уведомление в REFERRAL_CHAT_ID
    Добавлено: отображение реферера в основном уведомлении
    """
    try:
        data = await state.get_data()
        logger.info(f"Данные из состояния: {data}")

        email_raw = email or data.get('email')
        email_lower = email_raw.lower() if email_raw else None
        telegram_id = telegram_id or message.from_user.id

        if not email_lower or not telegram_id:
            await message.answer("❌ Не удалось получить email или Telegram ID.")
            return

        expiry_time = data.get('expiry_time')
        expiry_time_description = get_expiry_time_description(expiry_time)
        country_name = data.get('selected_country_name', 'Неизвестно')

        # Генерация конфига
        userdata, config, config2, config3 = await generate_config_from_pay(telegram_id, email_lower, state)
        await save_config_to_new_table(email_raw, config3)

        # Сообщение пользователю
        full_response = (
            f"⏳ {userdata}\n\n"
            f"<b>Нажмите на ссылку, чтоб скопировать:</b>\n\n"
            f"<pre><code>{config3}</code></pre>\n\n"
            f"Для получения инструкции выберите устройство👇"
        )
        if tickets_message:
            full_response += f"\n\nВы участвуете в розыгрыше, у вас 🎟️ {tickets_message}"

        payment_method = data.get('payment_method')
        if payment_method in ["tgpay", "star"]:
            await message.answer(full_response, parse_mode="HTML", disable_web_page_preview=True, reply_markup=get_instructions_button())
        else:
            await message.edit_text(full_response, parse_mode="HTML", disable_web_page_preview=True, reply_markup=get_instructions_button())

        # Получаем информацию о пользователе
        user = await bot.get_chat(telegram_id)
        full_name = user.full_name or f"Пользователь {telegram_id}"
        username = user.username
        user_link = f"<a href='tg://user?id={telegram_id}'>{full_name}</a>"
        username_text = f"@{username}" if username else "без юзернейма"

        # 🔍 Поиск реферера и формирование Telegram-ссылки
        referrer_link = None
        async with aiosqlite.connect(USERSDATABASE) as db:
            db.row_factory = aiosqlite.Row

            # Шаг 1: Получаем referrer_code текущего пользователя
            cursor = await db.execute(
                "SELECT referrer_code FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            result = await cursor.fetchone()

            if result and (referral_code := result["referrer_code"]):
                # Шаг 2: Находим пользователя, чей referral_code = referrer_code
                cursor = await db.execute(
                    "SELECT telegram_id, telegram_link FROM users WHERE referral_code = ?",
                    (referral_code,)
                )
                referrer = await cursor.fetchone()

                if referrer:
                    referrer_id = referrer["telegram_id"]
                    referrer_username = referrer["telegram_link"]

                    if referrer_username:
                        # Приоритет: ссылка через @username
                        telegram_link = f"{referrer_username}"
                        referrer_link = f'<a href="{telegram_link}">{referrer_username}</a>'
                    else:
                        # Резерв: deep link по ID
                        telegram_link = f"tg://user?id={referrer_id}"
                        referrer_link = f'<a href="{telegram_link}">Пользователь {referrer_id}</a>'
                else:
                    referrer_link = "реферер не найден"
            else:
                referrer_link = "не указан"

        # 📩 Отправка уведомления в основную группу
        try:
            await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=(
                    f"📩 <b>Пользователь</b> {user_link} оплатил подписку на {expiry_time_description} до {userdata}\n"
                    f"📧 Email: {email_raw}\n"
                    f"🔑 Ключ выдан ✅\n"
                    f"🌍 Сервер: {country_name}\n"
                    f"👥 Пришёл от: {referrer_link}"
                ),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"✅ Уведомление отправлено в GROUP_CHAT_ID: {GROUP_CHAT_ID}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в GROUP_CHAT_ID: {e}")

        # 🔍 Проверка referrer_code == 'eb1a1788' → уведомление в REFERRAL_CHAT_ID
        async with aiosqlite.connect(USERSDATABASE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT referred_by FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            result = await cursor.fetchone()

        if result and result["referred_by"] == "eb1a1788":
            logger.info(f"🎯 Пользователь {telegram_id} пришёл по referrer_code=eb1a1788 → отправляем в REFERRAL_CHAT_ID")
            try:
                await bot.send_message(
                    chat_id=REFERRAL_CHAT_ID,
                    text=(
                        f"🎯 <b>Новый реферал (eb1a1788)!</b>\n"
                        f"👤 Пользователь: {user_link}\n"
                        f"🆔 ID: <code>{telegram_id}</code>\n"
                        f"📧 Email: {email_raw}\n"
                        f"🔑 Ключ выдан ✅\n"
                        f"🌍 Сервер: {country_name}"
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                logger.info("✅ Уведомление отправлено в REFERRAL_CHAT_ID")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки в REFERRAL_CHAT_ID: {e}", exc_info=True)
        else:
            ref_code = result["referred_by"] if result else "не установлен"
            logger.info(f"🚫 referred_by={ref_code} ≠ eb1a1788 → уведомление не отправлено")

    except Exception as e:
        logger.error(f"❌ Ошибка в send_config_from_state: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке запроса.")