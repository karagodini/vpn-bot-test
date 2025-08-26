import aiohttp
import sqlite3
import  json
import asyncio
from aiogram import types
from handlers.config import get_server_data
from log import logger
from db.db import get_server_id, get_server_ids_as_list
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram import Router, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from handlers.select_server import get_optimal_server
from client.add_client import add_client
from db.db import emails_from_smena_servera, ServerDatabase
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from buttons.client import BUTTON_TEXTS
from dotenv import load_dotenv
import os, time

load_dotenv()

USERSDATABASE = os.getenv("USERSDATABASE")
SERVEDATABASE = os.getenv("SERVEDATABASE")

server_db = ServerDatabase(SERVEDATABASE)

router = Router()

@router.callback_query(lambda c: c.data == "smena_servera")
async def handle_get_config(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос на смену сервера. Отображает список логинов с возможностью выбора.
    Если для логина нет подписки, выводит сообщение о невозможности смены страны.
    """
    telegram_id = callback_query.from_user.id
    emails_with_servers = await emails_from_smena_servera(telegram_id)
    keyboard = InlineKeyboardBuilder()

    if emails_with_servers:
        valid_emails = []

        for entry in emails_with_servers:
            email = entry["email"]
            server_id = entry["server_id"]
            exists, is_expired = await email_exists_on_any_server(email)

            if exists and not is_expired:
                valid_emails.append(entry)

        if valid_emails:
            for entry in valid_emails:
                email = entry["email"]
                server_id = entry["server_id"]
                keyboard.add(
                    InlineKeyboardButton(
                        text=email,
                        callback_data=f"select_email:{email}:{server_id}"
                    )
                )

            keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="get_cabinet"))

            new_text = "Выберите логин, на котором хотите сменить страну:"
            if callback_query.message.text != new_text or callback_query.message.reply_markup != keyboard.as_markup():
                await callback_query.message.edit_text(
                    text=new_text,
                    reply_markup=keyboard.adjust(1).as_markup()
                )
        else:
            keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="get_cabinet"))
            new_text = "❌ Не удалось найти подписок, доступных для смены страны."
            if callback_query.message.text != new_text or callback_query.message.reply_markup != keyboard.as_markup():
                await callback_query.message.edit_text(
                    text=new_text,
                    reply_markup=keyboard.as_markup()
                )
    else:
        keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="get_cabinet"))
        new_text = "❌ Не удалось найти ваши подписки."
        if callback_query.message.text != new_text or callback_query.message.reply_markup != keyboard.as_markup():
            await callback_query.message.edit_text(
                text=new_text,
                reply_markup=keyboard.as_markup()
            )


async def email_exists_on_any_server(email: str) -> tuple[bool, bool]:
    """
    Проверяет существование логина на любых серверах и определяет, истекла ли его подписка.
    """
    server_ids_str = await get_server_id(SERVEDATABASE)  # Получаем строку "1,2,3"
    server_ids = [int(sid) for sid in server_ids_str.split(",") if sid.isdigit()]  # Преобразуем в список

    logger.info(f"Список серверов: {server_ids}")
    current_time_ms = int(time.time() * 1000)

    async def check_server(server_id):
        server_data = await get_server_data(server_id)
        if not server_data:
            logger.error(f"Данные сервера {server_id} не найдены.")
            return False, False

        LOGIN_DATA = {
            "username": server_data["username"],
            "password": server_data["password"],
        }

        async with aiohttp.ClientSession() as session:
            try:
                login_response = await session.post(server_data["login_url"], json=LOGIN_DATA)
                if login_response.status != 200:
                    logger.error(f"Ошибка входа на сервер {server_id}: {await login_response.text()}")
                    return False, False

                for inbound_id in server_data.get("inbound_ids", []):
                    inbound_url = f"{server_data['config_client_url']}/{inbound_id}"
                    inbound_response = await session.get(inbound_url, headers={'Accept': 'application/json'})

                    if inbound_response.status != 200:
                        logger.error(f"Ошибка получения inbound ID {inbound_id}: {await inbound_response.text()}")
                        continue

                    inbound_data = await inbound_response.json()
                    if inbound_data.get("obj") is None:
                        logger.error(f"Нет данных для inbound ID {inbound_id}")
                        continue

                    clients = json.loads(inbound_data["obj"]["settings"]).get("clients", [])
                    for client in clients:
                        if client["email"] == email:
                            expiry_time = int(client.get("expiryTime", 0))
                            is_expired = expiry_time < current_time_ms
                            return True, is_expired

                return False, False

            except Exception as e:
                logger.error(f"Ошибка при проверке email {email} на сервере {server_id}: {e}")
                return False, False

    results = await asyncio.gather(*[check_server(server_id) for server_id in server_ids])
    for exists, is_expired in results:
        if exists:
            return exists, is_expired
    return False, False

@router.callback_query(lambda c: c.data.startswith("select_email:"))
async def handle_select_email(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор логина для смены страны. Отображает доступные страны для выбора.
    """
    data = callback_query.data.split(":")
    email = data[1]
    current_server_id = int(data[2])
    logger.info(f"Полученный current_server_id: {current_server_id}")
    telegram_id = callback_query.from_user.id
    server_data = await get_server_data(current_server_id)
    server_name = server_data['name']
    if not server_data:
        await callback_query.message.edit_text(
            text="❌ Не удалось найти данные для выбранного сервера. Попробуйте снова."
        )
        return
    userdata = await fetch_client_data(telegram_id, email, server_data, state)
    
    if not userdata:
        await callback_query.message.edit_text(
            text="❌ Не удалось найти данные для этого логина. Попробуйте снова.",
        )
        return
    keyboard = await generate_countries_keyboard(current_server_id)

    await callback_query.message.edit_text(
        text=f"Вы выбрали логин: {email}\nТекущая страна: {server_name}.\nВыберите новую страну:",
        reply_markup=keyboard
    )


async def generate_countries_keyboard(current_server_id: int) -> InlineKeyboardMarkup:
    """
    Генерирует клавиатуру для выбора страны (сервера) для смены.
    """
    keyboard = InlineKeyboardBuilder()
    current_server_id_str = str(current_server_id)
    server_ids = await get_server_ids_as_list(SERVEDATABASE)
    logger.info(f"Список серверов: {server_ids}")

    for server_id in server_ids:
        if str(server_id) == current_server_id_str:
            logger.info(f"Пропускаем сервер ID: {server_id} (текущий сервер)")
            continue
        server_data = await get_server_data(server_id)
        if server_data:
            country_name = server_data['name']
            logger.info(f"Добавляем сервер: {country_name} (ID: {server_id})")
            keyboard.add(InlineKeyboardButton(text=country_name, callback_data=f"select_country_{server_id}"))

    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="smena_servera"))
    return keyboard.adjust(1).as_markup()


@router.callback_query(lambda c: c.data.startswith("select_country_"))
async def select_country(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор новой страны (сервера) для клиента.
    """
    server_id = callback_query.data.split("_")[-1] 
    state_data = await state.get_data()
    selected_server_id = state_data.get('server_id')

    await state.update_data(new_server_id=server_id)
    state_data = await state.get_data()
    new_server_id = state_data.get("new_server_id")

    optimal_server = await get_optimal_server(new_server_id, server_db)

    if isinstance(optimal_server, str) and not optimal_server.isdigit():  
        await callback_query.message.edit_text(
            text="⚠️ В данной локации нет свободных серверов. Попробуйте позже или выберите другую страну.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="get_cabinet")]
                ]
            )
        )
        return

    # Получаем данные по серверам
    server_data = await get_server_data(selected_server_id)
    new_server_data = await get_server_data(optimal_server)
    server_name = new_server_data['name']

    # Создаём новый логин и удаляем клиента со старого сервера
    await new_email(telegram_id=callback_query.from_user.id, server_data=new_server_data, state=state)
    delete_success = await delete_client(telegram_id=callback_query.from_user.id, server_data=server_data, state=state)

    # Проверяем успешность удаления клиента
    if delete_success:
        await callback_query.message.edit_text(
            text=f"✅ Подписка перемещена в страну {server_name}.\nНовые ключи в личном кабинете.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=BUTTON_TEXTS["cabinet"], callback_data="cabinet")]
                ]
            )
        )
    else:
        await callback_query.message.edit_text(
            text="❌ Не удалось удалить клиента. Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="get_cabinet")]
                ]
            )
        )

@router.callback_query(lambda c: c.data == "change_country")
async def change_country(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обработчик для изменения страны и переноса клиента на новый сервер.

    Этот метод выполняет следующие действия:
    - Извлекает данные из состояния FSM.
    - Проверяет наличие всех необходимых данных (сервер, клиент, inbound).
    - Обновляет логин клиента на новый сервер и удаляет клиента с текущего сервера.
    - Отправляет уведомление о результате операции.
    """

    state_data = await state.get_data()
    selected_server_id = state_data.get('server_id')
    client_id = state_data.get('client_id')
    inbound_id = state_data.get('inbound_id')

    new_server_id = state_data.get('new_server_id')
    
    if not selected_server_id or not client_id or not inbound_id:
        await callback_query.message.edit_text(
            text="❌ У вас нет выбранного сервера или клиента для удаления. Попробуйте выбрать сервер сначала."
        )
        return
    server_data = await get_server_data(selected_server_id)

    new_server_data = await get_server_data(new_server_id)
    if not server_data:
        await callback_query.message.edit_text(
            text="❌ Не удалось найти данные сервера. Попробуйте позже."
        )
        return
    await new_email(telegram_id=callback_query.from_user.id, server_data=new_server_data, state=state)

    delete_success = await delete_client(telegram_id=callback_query.from_user.id, server_data=server_data, state=state)
    
    if delete_success:
        await callback_query.message.edit_text(
            text="✅ Клиент успешно удален с сервера. Выберите другой сервер или выполните другие действия.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="smena_servera")]
                ]
            )
        )
    else:
        await callback_query.message.edit_text(
            text="❌ Не удалось удалить клиента. Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="smena_servera")]
                ]
            )
        )


async def new_email(telegram_id, server_data, state: FSMContext):
    """
    Обработчик для обновления логина клиента на новый сервер и добавления его на новый сервер.

    Этот метод выполняет следующие действия:
    - Извлекает необходимые данные из состояния FSM.
    - Обновляет запись логина в базе данных с новым сервером.
    - Добавляет клиента на новый сервер через API.
    """

    logger.info(f"Начинаем обработку запроса для Telegram ID: {telegram_id}")

    state_data = await state.get_data()
    logger.info(f"Данные из состояния FSM: {state_data}")
    client_id = state_data.get('client_id')
    new_server_id = state_data.get('new_server_id')
    expiry_time = state_data.get('expiry_time')
    email = state_data.get('email')

    if not client_id or not new_server_id:
        logger.error("Отсутствуют необходимые данные (client_id или new_server_id) в состоянии FSM.")
        return None
    server_data = await get_server_data(new_server_id)
    if not server_data:
        logger.error(f"Не удалось получить данные для нового сервера с ID: {new_server_id}")
        return None
    LOGIN_URL = server_data.get('login_url')
    ADD_CLIENT_URL = server_data.get("add_client_url")
    logger.info(f"{ADD_CLIENT_URL}   Данные для входа на сервер: {LOGIN_URL}, username: {server_data.get('username')}")
    conn = sqlite3.connect(USERSDATABASE)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE user_emails
            SET id_server = ?
            WHERE email = ?
        """, (new_server_id, email))
        conn.commit()
        logger.info(f"Обновлен id_server для email: {email} на значение {new_server_id}")
    except Exception as e:
        logger.error(f"Ошибка обновления id_server для email {email}: {e}")
    finally:
        cursor.close()
        conn.close()

    await add_client(
        email, expiry_time, server_data['inbound_ids'], telegram_id,
        server_data['add_client_url'], server_data['login_url'], 
        {"username": server_data['username'], "password": server_data['password']}
    )


async def delete_client(telegram_id, server_data, state: FSMContext):
    """
    Обработчик для удаления клиента с сервера.

    Этот метод выполняет следующие действия:
    - Извлекает данные из состояния FSM.
    - Производит вход на сервер с использованием учетных данных.
    - Удаляет клиента с сервера через API.
    - Обновляет состояние FSM после успешного удаления клиента.
    """
    state_data = await state.get_data()
    inbound_id = state_data.get("inbound_id")
    client_id = state_data.get("client_id")

    if inbound_id and client_id:
        LOGIN_URL = server_data.get('login_url')
        logger.info(f"LOGIN_URL: {LOGIN_URL}")
        login_data = {
            'username': server_data['username'],
            'password': server_data['password']
        }
        logger.info(f"Login data: {login_data}")
        async with aiohttp.ClientSession() as session:
            try:
                login_response = await session.post(LOGIN_URL, json=login_data)
                logger.info(f"Login response status: {login_response.status}")

                if login_response.status == 200:
                    session_id = login_response.cookies.get("3x-ui")
                    delete_url = f"{server_data.get('base_url')}/panel/api/inbounds/{inbound_id}/delClient/{client_id}"

                    if not delete_url:
                        logger.error("URL для удаления клиента отсутствует в данных сервера.")
                        return False
                    logger.info(f"URL для удаления клиента: {delete_url}")
                    response = await session.post(delete_url, cookies={"3x-ui": session_id})

                    if response.status == 200:
                        logger.info(f"Клиент с ID {client_id} успешно удален.")
                        
                        await state.update_data(client_id=None, inbound_id=None)
                        return True
                    elif response.status == 404:
                        logger.error(f"Не найден ресурс для удаления клиента: {delete_url}")
                        return False
                    else:
                        logger.error(f"Ошибка при удалении клиента: {response.status} - {response.text}")
                        return False
                else:
                    logger.error(f"Ошибка при входе перед удалением клиента. Статус: {login_response.status} - {login_response.text}")
                    return False
            except Exception as e:
                logger.error(f"Ошибка при запросе для удаления клиента: {str(e)}")
                return False
    else:
        logger.error(f"Недостаточно данных для удаления клиента: inbound_id или client_id отсутствуют.")
        return False


async def fetch_client_data(telegram_id, email, server_data, state: FSMContext):
    """
    Получает данные клиента с сервера для указанного email.

    Этот метод выполняет следующие действия:
    - Производит вход на сервер с использованием учетных данных.
    - Получает конфигурацию клиента с сервера, используя email клиента.
    """
    LOGIN_DATA = {
        "username": server_data["username"],
        "password": server_data["password"],
    }

    async with aiohttp.ClientSession() as session:
        login_response = await session.post(server_data["login_url"], json=LOGIN_DATA)

        if login_response.status != 200:
            logger.error(f"Ошибка входа: {await login_response.text()}")
            return None, []
        userdata = await get_client_config(telegram_id, email, server_data, session, state)
        return userdata


async def get_client_config(telegram_id, email, server_data, session, state: FSMContext):
    """
    Получает конфигурацию клиента на сервере по логину.

    Этот метод выполняет следующие действия:
    - Проходит по всем inbound ID на сервере.
    - Получает данные конфигурации клиента с сервера.
    - Обновляет состояние FSM с данными клиента.
    """
    all_inbound_ids = server_data.get("inbound_ids", [])
    for inbound_id in all_inbound_ids:
        inbound_url = f"{server_data['config_client_url']}/{inbound_id}"
        inbound_response = await session.get(inbound_url, headers={'Accept': 'application/json'})

        if inbound_response.status != 200:
            logger.error(f"Ошибка получения данных inbound для ID {inbound_id}: {await inbound_response.text()}")
            continue
        inbound_data = await inbound_response.json()
        if not inbound_data.get('obj'):
            continue
        client = next((c for c in json.loads(inbound_data['obj']['settings']).get('clients', []) if c['email'] == email), None)

        if client:
            await state.update_data(
                client_id=client.get('id'),
                email=email,
                expiry_time=client.get('expiryTime', 'N/A'),
                sub_id=client.get('subId', 'N/A'),
                telegram_id=telegram_id,
                inbound_id=inbound_id,
                server_id=server_data.get('id', 'N/A'),
            )
            state_data = await state.get_data()
            logger.info(f"Данные FSM после обновления: {state_data}")
            break
    return await state.get_data()