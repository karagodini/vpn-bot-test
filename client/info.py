from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile, InlineKeyboardButton
from handlers.config import get_server_data
from db.db import get_server_ids_as_list
from buttons.client import BUTTON_TEXTS
from bot import bot
from client.menu import get_back_button
import aiohttp
import asyncio
from aiogram.enums import ChatAction
from log import logger
from dotenv import load_dotenv
import os
from client.text import SERVICE_TEXT, PRICE_TEXT
from aiogram.enums.parse_mode import ParseMode

load_dotenv()

# Загрузка переменных окружения
ANDR = os.getenv("ANDR")
LINUX = os.getenv("LINUX")
WINDOWS = os.getenv("WINDOWS")
MAC = os.getenv("MAC")
IOS = os.getenv("IOS")
SERVEDATABASE = os.getenv("SERVEDATABASE")


async def check_server_status(server_url: str, server_name: str) -> str:
    """
    Проверяет статус сервера по его URL.
    
    :param server_url: URL сервера
    :param server_name: Название сервера
    :return: Статус сервера (онлайн/оффлайн)
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(server_url) as response:
                if response.status == 200:
                    return f"🟢 Сервер {server_name}: онлайн"
                else:
                    return f"🔴 Сервер {server_name}: недоступен"
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка при проверке сервера {server_name}: {e}")
        return f"🔴 Сервер {server_name}: в данный момент недоступен"


async def check_all_servers() -> dict:
    """
    Проверяет статус всех серверов.
    """
    server_ids = await get_server_ids_as_list(SERVEDATABASE)
    statuses = {}

    tasks = []
    for server_id in server_ids:
        server_data = await get_server_data(server_id)
        if server_data:
            server_url = server_data["server"]
            server_name = server_data["name"]
            tasks.append(check_server_status(server_url, server_name))
        else:
            statuses[server_id] = f"🔴 Сервер с ID {server_id} не найден"

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for server_id, result in zip(server_ids, results):
        if isinstance(result, str):
            statuses[server_id] = result

    return statuses

async def show_server_info(callback_query: types.CallbackQuery):
    """
    Отображает информацию о серверах и условиях использования VPN.
    """
    server_info_text = SERVICE_TEXT
    statuses = await check_all_servers()
    status_text = "\n".join(statuses.values())

    final_text = f"🌐 Статус серверов:\n\n{status_text}\n\n{server_info_text}\n"

    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=final_text,
        parse_mode=ParseMode.HTML, 
        disable_web_page_preview=True,
        reply_markup=get_back_button()
    )

async def show_router_instructions(callback_query: types.CallbackQuery):
    """
    Отображает информацию о серверах и условиях использования VPN.
    """
    server_info_text = SERVICE_TEXT
    statuses = await check_all_servers()
    status_text = "\n".join(statuses.values())

    final_text = f"🌐 Статус серверов:\n\n{status_text}\n\n{server_info_text}\n"

    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=final_text,
        parse_mode=ParseMode.HTML, 
        disable_web_page_preview=True,
        reply_markup=get_back_button()
    )


def get_instruction_menu_keyboard() -> InlineKeyboardBuilder:
    """
    Создает клавиатуру для меню инструкций.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["ios"], url=IOS),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["android"], url=ANDR),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["macos"], url=MAC),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["windows"], url=WINDOWS),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["linux"], url=LINUX),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="get_cabinet")
    )
    keyboard.adjust(2, 2, 1)
    return keyboard


async def show_instructions(callback_query: types.CallbackQuery):
    """
    Отображает меню с инструкциями для разных операционных систем.
    """
    await callback_query.message.answer("📄 Инструкция по подключению:")
    await callback_query.message.answer(
    "Вы выбрали: iPhone 📱\n\n"
    "Загрузите приложение <a href=\"https://apps.apple.com/us/app/v2raytun/id6476628951\">v2RayTun</a> на свой iPhone.\n\n"
    "Вы можете нажать на ссылку выше или самостоятельно найти это приложение в App Store.",
    parse_mode="HTML"
)

    await bot.send_photo(
        chat_id=callback_query.message.chat.id,
        photo=FSInputFile("client/images/vpn1.jpg"),
        parse_mode="HTML"
    )

    await bot.send_photo(
        chat_id=callback_query.message.chat.id,
        caption="Теперь запускаем приложение v2RayTun",
        photo=FSInputFile("client/images/vpn2.jpg"),
        parse_mode="HTML"
    )

    await bot.send_photo(
        chat_id=callback_query.message.chat.id,
        caption="Нажимаем на «плюс» в верхнем правом углу, предварительно скопировав ключ в боте и нажимаем - «добавить из буфера»",
        photo=FSInputFile("client/images/vpn3.jpg"),
        parse_mode="HTML"
    )

    await bot.send_photo(
        chat_id=callback_query.message.chat.id,
        caption="После нажатия на «Разрешить вставку» нажмите на «Кнопку запуска»",
        photo=FSInputFile("client/images/vpn4.jpg"),
        parse_mode="HTML"
    )

    await bot.send_photo(
        chat_id=callback_query.message.chat.id,
        caption="В появившемся окне «Запрос разрешения на добавление конфигураций VPN» нажмите «Разрешить»",
        photo=FSInputFile("client/images/vpn5.jpg"),
        parse_mode="HTML"
    )

    await bot.send_photo(
        chat_id=callback_query.message.chat.id,
        caption="Когда сервер подключен, то «Кнопка запуска» станет зеленым цветом.\nВот так всё просто! Ваш VPN работает и правильно настроен!",
        photo=FSInputFile("client/images/vpn6.jpg"),
        parse_mode="HTML"
    )

    await callback_query.message.answer(
    "✅ Инструкция завершена. Вы можете вернуться в главное меню.",
    reply_markup=get_back_button()
)



async def show_prices(callback_query: types.CallbackQuery):
    """
    Отображает информацию о ценах на подписки.
    """
    prices_text = PRICE_TEXT
    # Убрать комменты и тогда при нажатии на кнопку "💰 Цены на услуги: будет статус, печатает...
    # Как пример, если хотите такое себе)
    #bot = callback_query.bot
    #chat_id = callback_query.message.chat.id

    #await bot.send_chat_action(chat_id, ChatAction.TYPING)
    #await asyncio.sleep(5)

    await callback_query.message.edit_text(
        text=prices_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_back_button()
    )
