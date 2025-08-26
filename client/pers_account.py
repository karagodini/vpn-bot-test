import aiohttp
import asyncio
import json
from datetime import datetime as dt
from aiogram import types
from handlers.config import get_server_data
from log import logger
from db.db import Database, get_server_ids_as_list
from aiogram import Router
from dotenv import load_dotenv
import os

load_dotenv()

AUTOHIDDIFY = os.getenv("AUTOHIDDIFY")
AUTOSTREI = os.getenv("AUTOSTREI")
USERSDATABASE = os.getenv("USERSDATABASE")
SERVEDATABASE = os.getenv("SERVEDATABASE")

router = Router()
semaphore = asyncio.Semaphore(10)

async def process_email_for_all_servers(callback_query: types.CallbackQuery, email: str) -> str:
    """
    Обрабатывает логин для конкретных серверов, связанных с указанным email.
    """
    db = Database(USERSDATABASE)
    client_server_pairs = await db.get_ids_by_email(email)

    if not client_server_pairs:
        return f"❌ Не удалось найти клиента с указанным логином: {email}."

    tasks = [
        process_server_with_semaphore(server_id, client_id, email, callback_query)
        for client_id, server_id in client_server_pairs
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    full_response = "\n\n".join(filter(None, [str(response) if isinstance(response, str) else "" for response in responses]))

    return full_response

async def process_server_with_semaphore(server_id, client_id, email, message):
    """
    Обрабатывает сервер с использованием семафора для ограничения количества одновременных запросов, чтобы избежать перегрузки системы.
    """
    async with semaphore:
        return await process_server(server_id, client_id, email, message)

async def process_server(server_id, client_id, email, message: types.Message):
    """
    Обрабатывает данные сервера для клиента, собирает и форматирует информацию о сервере и подписке, а также отправляет ответ пользователю.
    """
    try:
        server_data = await get_server_data(server_id)
        if not server_data:
            logger.error(f"Данные сервера не найдены для server_id: {server_id}")
            return ""

        userdata_list, config_list = await config_from_lk(client_id, email, server_data)

        if userdata_list and config_list:
            server_name = server_data['name']
            response = format_response(email, server_name, userdata_list, config_list)
            return response
        else:
            logger.info(f"Обработка сервера {server_id}")
    except Exception as e:
        logger.error(f"Ошибка при обработке сервера {server_id} для клиента {client_id}: {e}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.", parse_mode="HTML")

    return ""

def format_response(email: str, server_name: str, userdata_list: list, config_list: list) -> str:
    """
    Форматирует ответ для отправки пользователю, включая информацию о логине, стране (сервере) и деталях подписки. Добавляет ссылки на автоконфигурацию для устройств iPhone и Android.
    """
    response = f"<b>Ваш Логин 🔑:</b> <code>{email}</code>\n"
    response += f"<b>Страна:</b> {server_name}\n"
    
    if userdata_list and "❌ Подписка неактивна" in userdata_list[0]:
        response += userdata_list[0]
        return response

    response += "\n".join(userdata_list)

    if len(config_list) > 1:
        response += (
            f"\n\n<b>Для IPhone — Streisand:</b>\n<code>{config_list[0]}</code>\n"
            f"<b>Для ANDROID — Hiddify:</b>\n<code>{config_list[1]}</code>\n"
            f"<b>Ссылка 🔑 для ручной настройки:</b>\n<code>{config_list[2]}</code>\n\n"
            f"<a href='{AUTOSTREI}{config_list[0]}'>Автонастройка IPhone — Streisand</a>\n"
            f"<a href='{AUTOHIDDIFY}{config_list[1]}'>Автонастройка ANDROID — Hiddify</a>\n"
            f"➖➖➖➖➖➖➖➖➖➖"
        )
    elif len(config_list) == 1:
        response += f"\n\n<code>{config_list[0]}</code>"

    return response

async def config_from_lk(client_id, email, server_data):
    """
    Получает конфигурацию клиента из личного кабинета, выполняет авторизацию и собирает данные о пользователе и конфигурации.
    """
    LOGIN_DATA = {
        "username": server_data["username"],
        "password": server_data["password"],
    }

    async with aiohttp.ClientSession() as session:
        try:
            login_response = await session.post(server_data["login_url"], json=LOGIN_DATA)
            if login_response.status != 200:
                logger.error("Ошибка входа: " + await login_response.text())
                return [], []

            userdata_list, config_list = [], []
            result = await get_client_config(client_id, email, server_data, session)
            userdata, config_url, config_json, config_vless = result

            if userdata:
                userdata_list.append(userdata)
                config_list.extend([config_json, config_url, config_vless])

            return userdata_list, config_list
        except Exception as e:
            logger.error(f"Ошибка при получении конфигурации: {e}")
            return [], []


async def get_client_config(email, server_data, session):
    """
    Получает конфигурацию клиента с сервера, включая данные о подписке, порте и настройках безопасности. 
    Формирует информацию о подписке и возвращает ссылки для автоконфигурации.
    """
    all_inbound_ids = server_data.get("inbound_ids", [])
    
    for inbound_id in all_inbound_ids:
        try:
            inbound_url = f"{server_data['config_client_url']}/{inbound_id}"
            inbound_response = await session.get(inbound_url, headers={'Accept': 'application/json'})

            if inbound_response.status != 200:
                logger.error(f"Ошибка получения данных inbound для ID {inbound_id}: {await inbound_response.text()}")
                continue

            inbound_data = await inbound_response.json()
            if inbound_data.get('obj') is None:
                logger.info(f"Нет данных для inbound ID {inbound_id}")
                continue

            clients = json.loads(inbound_data['obj']['settings']).get('clients', [])
            client = next((c for c in clients if c['email'] == email), None)

            if not client:
                continue
            
            expiry_time = client.get('expiryTime', 0)
            current_time = int(dt.utcnow().timestamp() * 1000)

            if expiry_time < current_time:
                expiry_text = "❌ Подписка неактивна (срок истек).\n➖➖➖➖➖➖➖➖➖➖"
                return expiry_text, "", "", ""

            port = inbound_data['obj']['port']
            stream_settings = json.loads(inbound_data['obj']['streamSettings'])
            sub_id = client.get('subId', '')

            expiry_text = f"📅 Подписка до: {dt.fromtimestamp(expiry_time / 1000).strftime('%Y-%m-%d %H:%M:%S')}"
            config_url = f"{server_data['sub_url']}{sub_id}\n"
            config_json = f"{server_data['json_sub']}{sub_id}\n"
            config_vless = (
                f"vless://{client['id']}@{server_data['server_ip']}:{port}?type={stream_settings['network']}&security={stream_settings['security']}"
                f"&pbk={stream_settings['realitySettings']['settings']['publicKey']}&fp={stream_settings['realitySettings']['settings']['fingerprint']}&"
                f"sni={stream_settings['realitySettings']['serverNames'][0]}&sid={stream_settings['realitySettings']['shortIds'][0]}&"
                f"spx={stream_settings['realitySettings']['settings']['spiderX'].replace('/', '%2F')}&flow=xtls-rprx-vision#{email}\n"
            )

            expiry_text = f"\n{expiry_text}"

            return expiry_text, config_url, config_json, config_vless
        except Exception as e:
            logger.error(f"Ошибка при обработке inbound ID {inbound_id}: {e}")
            continue

    return "", "", "", ""
