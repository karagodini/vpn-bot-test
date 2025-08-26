"""
Модуль для управления серверами в боте.

Функционал:
- Отображение меню управления серверами для администраторов.
- Добавление нового сервера с валидацией данных.
- Изменение списка серверов с которыми буде работать бот.
- Редактирование параметров существующих серверов.
- Удаление серверов.
- Просмотр полной информации о серверах и кластерах.
- Управление группами(кластерами) серверов.

"""

from aiogram import types
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
import re
from db.db import  ServerDatabase
from aiogram import Router
from log import logger
from bot import bot
from handlers.states import  AddServerState, ChangeServerIdsState, EditServerState, ServerGroupForm
from buttons.admin import BUTTON_TEXTS
from admin.servers_func import *
from dotenv import load_dotenv
import os

load_dotenv()

SERVEDATABASE = os.getenv("SERVEDATABASE")
router = Router()
server_db = ServerDatabase(SERVEDATABASE)


@router.message(lambda message: message.text == BUTTON_TEXTS["work_with_servers"])
async def start_handler(message: types.Message, state: FSMContext):
    await message.delete()

    """Отображает начальное меню с доступными опциями"""
    keyboard = InlineKeyboardBuilder().add(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["add_server"], 
            callback_data="add_server"
        ),
        InlineKeyboardButton(
            text=BUTTON_TEXTS["change_server_ids"], 
            callback_data="change_server_ids"
        ),
        InlineKeyboardButton(
            text=BUTTON_TEXTS["change_group_server"], 
            callback_data="change_group_server"
        ),
        InlineKeyboardButton(
            text=BUTTON_TEXTS["cluster_delete"], 
            callback_data="cluster_delete"
        ),
        InlineKeyboardButton(
            text=BUTTON_TEXTS["show_servers_info"], 
            callback_data="show_full_servers_info"
        ),
        InlineKeyboardButton(
            text=BUTTON_TEXTS["edit_server"],
            callback_data="edit_server"
        ),
        InlineKeyboardButton(
            text=BUTTON_TEXTS["d_server"],
            callback_data="d_server"
        )
    )

    sent_message = await message.answer(
        "Привет! Что вы хотите сделать? Выберите нужную опцию:",
        reply_markup=keyboard.adjust(1).as_markup()
    )

    await state.update_data(
        sent_message_id=sent_message.message_id,
        chat_id=sent_message.chat.id
    )


@router.callback_query(lambda c: c.data == "add_server")
async def add_server_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Начало добавления сервера"""
    await callback_query.answer()
    cancel_button = InlineKeyboardBuilder().add(
        InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel_admin")
    )
    user_data = await state.get_data()
    sent_message_id = user_data.get('sent_message_id')
    await callback_query.message.edit_text(
        "Пожалуйста, введите данные сервера в следующем формате:\n\n"
        "`id, total_slots, name, username, password, server_ip, base_url, subscription_base, sub_url, json_sub, inbound_ids`\n\n"
        "Где:\n"
        "- `id`: Уникальный номер сервера (целое число, например, `1`).\n"
        "- `total_slots`: Общее количество мест (целое число, например, `100`).\n"
        "- `name`: Название сервера (например, `🇩🇪 Германия`).\n"
        "- `username`: Логин для доступа к серверу (например, `admin`).\n"
        "- `password`: Пароль для доступа к серверу (например, `securepass`).\n"
        "- `server_ip`: IP-адрес сервера или домен (например, так `192.168.1.1` или так `top.vpn.online`).\n"
        "- `base_url`: Базовый URL сервера (например, `https://top.vpn.online:22053`).\n"
        "- `subscription_base`: URL подписки (например, `https://top.vpn.online:2096`).\n"
        "- `sub_url`: Путь до подписки (например, `/sub/`).\n"
        "- `json_sub`: Путь до json подписки (например, `/json/`).\n"
        "- `inbound_ids`: ID(номер) созданного подключения VLESS для платных ключей (например, `2`).\n\n"
        "Пример ввода:\n"
        "`1, 100, 🇩🇪 Германия, admin, securepass, 192.168.1.1, https://top.vpn.online:22053, https://top.vpn.online:2096, /sub/, /json/, 2`\n\n"
        "Если всё понятно, введите данные сервера в указанном формате.",
        parse_mode="Markdown", reply_markup=cancel_button.as_markup()
    )
    await state.update_data(sent_message_id=sent_message_id, chat_id=callback_query.message.chat.id)
    await state.set_state(AddServerState.waiting_for_data)


@router.callback_query(lambda c: c.data == "change_server_ids")
async def change_server_ids_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик изменения server_ids(списка серверов)"""
    await callback_query.answer()

    current_server_ids = get_current_server_ids()
    cancel_button = InlineKeyboardBuilder().add(
        InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel_admin")
    )
    current_ids_text = ", ".join(map(str, current_server_ids)) if current_server_ids else "Нет серверов"
    user_data = await state.get_data()
    sent_message_id = user_data.get('sent_message_id')
    sent_message = await callback_query.message.edit_text(
        f"Текущие server_ids: `{current_ids_text}`\n\n"
        "Введите новое значение server_ids в формате списка, разделённого запятыми (например, `1,2,3`):",parse_mode="Markdown",
        reply_markup=cancel_button.as_markup()
    )
    await state.update_data(sent_message_id=sent_message.message_id, chat_id=callback_query.message.chat.id)
    await state.set_state(ChangeServerIdsState.waiting_for_server_ids)

@router.message(ChangeServerIdsState.waiting_for_server_ids)
async def process_server_ids(message: types.Message, state: FSMContext):
    """Обработка нового значения server_ids"""
    try:
        server_ids = list(map(int, message.text.split(',')))
        update_server_ids_in_db(server_ids)
        user_data = await state.get_data()
        sent_message_id = user_data.get('sent_message_id')
        chat_id = user_data.get('chat_id')
        if sent_message_id and chat_id:
            await message.bot.delete_message(chat_id=chat_id, message_id=sent_message_id)
        await message.answer(f"✅ Значение server_ids успешно обновлено на: {', '.join(map(str, server_ids))}")
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка обновления server_ids: {e}")
        await message.answer("❌ Произошла ошибка при обновлении значения server_ids. Проверьте формат ввода и попробуйте снова.")


@router.message(AddServerState.waiting_for_data)
async def process_server_data(msg: types.Message, state: FSMContext):
    """Обработка введённых данных для добавления сервера"""
    try:
        data = msg.text.split(", ")
        server_data = {
            "id": int(data[0]),
            "total_slots": int(data[1]),
            "name": data[2],
            "username": data[3],
            "password": data[4],
            "server_ip": data[5],
            "base_url": data[6],
            "subscription_base": data[7],
            "subscription_urls": {
                "sub_url": data[8],
                "json_sub": data[9],
            },
            "inbound_ids": list(map(int, data[10].split(";"))),
        }
        server_db.add_server(server_data)

        await msg.answer("✅ Сервер успешно добавлен!")
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка добавления сервера: {e}")
        await msg.answer("❌ Произошла ошибка при добавлении сервера. Проверьте формат ввода и попробуйте снова.")


@router.callback_query(lambda c: c.data == "show_full_servers_info")
async def show_full_servers_info_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Отображение полной информации о серверах и кластерах(группах)."""
    await callback_query.answer()

    server_info = get_full_server_info()
    if server_info:
        servers_text = "Информация о серверах:\n\n"
        for server in server_info:
            servers_text += (
                f"ID: {server['id']}\n"
                f"Название: {server['name']}\n"
                f"Мест: {server['total_slots']}\n"
                f"Логин: {server['username']}\n"
                f"Пароль: {server['password']}\n"
                f"IP: {server['server_ip']}\n"
                f"Base URL: {server['base_url']}\n"
                f"Subscription Base: {server['subscription_base']}\n"
                f"Sub URL: {server['sub_url']}\n"
                f"JSON Sub: {server['json_sub']}\n"
                f"Inbound VLESS ID: {server['inbound_ids']}\n\n"
            )
    else:
        servers_text = "Сервера не найдены.\n\n"

    server_groups = get_server_groups()
    if server_groups:
        clusters_text = "Информация о кластерах:\n\n"
        for group in server_groups:
            clusters_text += (
                f"Номер сервера: {group['group_name']}\n"
                f"Серверы в кластере: {group['server_ids']}\n\n"
            )
    else:
        clusters_text = "Кластеры не найдены.\n\n"
    await callback_query.message.answer(f"{servers_text}\n{clusters_text}")
    
@router.callback_query(lambda c: c.data == "edit_server")
async def edit_server_select(callback_query: types.CallbackQuery, state: FSMContext):
    """Запрашивает выбор сервера для редактирования"""
    await callback_query.answer()
    servers = get_servers()
    if not servers:
        await callback_query.message.edit_text("❌ Нет доступных серверов для редактирования.")
        return
    keyboard = InlineKeyboardBuilder()
    for server in servers:
        server_id, server_name = server
        keyboard.add(InlineKeyboardButton(text=f"{server_name} (ID: {server_id})", callback_data=f"select_server_{server_id}"))
    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel_admin"))
    sent_message = await callback_query.message.edit_text(
        "Выберите сервер, который хотите редактировать:",
        reply_markup=keyboard.adjust(1).as_markup()
    )
    await state.update_data(sent_message_id=sent_message.message_id, chat_id=callback_query.message.chat.id)


@router.callback_query(lambda c: c.data.startswith("select_server_"))
async def select_server_for_edit(callback_query: types.CallbackQuery, state: FSMContext):
    """Запрашивает параметр для редактирования выбранного сервера"""
    await callback_query.answer()
    server_id = int(callback_query.data.split("_")[-1])

    await state.update_data(server_id=server_id)
    cancel_button = InlineKeyboardBuilder().add(
        InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel_admin")
    )
    await callback_query.message.edit_text(
        f"Вы выбрали сервер с ID: {server_id}. Что вы хотите изменить?\n\n"
        "Параметры: `total_slots`, `name`, `username`, `password`, `server_ip`, `base_url`, `subscription_base`, `sub_url`, `json_sub`, `inbound_ids`\n\n"
        "Введите название параметра (например, `total_slots`) и новое значение, разделённые запятой.\n"
        "Пример: `total_slots, 150`",
        parse_mode="Markdown",
        reply_markup=cancel_button.as_markup()
    )

    await state.set_state(EditServerState.waiting_for_param)

@router.message(EditServerState.waiting_for_param)
async def process_edit_server_param(msg: types.Message, state: FSMContext):
    """Обработка данных для редактирования параметра у сервера"""
    try:
        data = msg.text.split(", ")
        if len(data) != 2:
            await msg.answer("❌ Неверный формат. Пожалуйста, введите параметр и новое значение, разделённые запятой.\nПример: `total_slots, 150`", parse_mode="Markdown")
            return

        param = data[0].strip()
        new_value = data[1].strip()

        user_data = await state.get_data()
        server_id = user_data.get("server_id")

        valid_params = ["total_slots", "name", "username", "password", "server_ip", "base_url", "subscription_base", "sub_url", "json_sub", "inbound_ids"]
        if param not in valid_params:
            await msg.answer(f"❌ Неверный параметр. Пожалуйста, выберите один из следующих: {', '.join(valid_params)}.")
            return
        success = update_server_data(server_id, param, new_value)

        if success:
            await msg.answer(f"✅ Параметр '{param}' успешно обновлён на '{new_value}'.")
        else:
            await msg.answer("❌ Произошла ошибка при обновлении данных. Попробуйте снова.")
        await state.clear()
    
    except Exception as e:
        print(f"Ошибка: {e}")
        await msg.answer("❌ Произошла ошибка при обработке данных. Пожалуйста, проверьте формат и попробуйте снова.")


@router.callback_query(lambda c: c.data == "d_server")
async def delete_server_select(callback_query: types.CallbackQuery, state: FSMContext):
    """Запрашивает выбор сервера для удаления"""
    await callback_query.answer()
    servers = get_servers()
    if not servers:
        await callback_query.message.edit_text("❌ Нет доступных серверов для удаления.")
        return

    keyboard = InlineKeyboardBuilder()
    for server in servers:
        server_id, server_name = server
        keyboard.add(InlineKeyboardButton(text=f"{server_name} (ID: {server_id})", callback_data=f"select_delete_server_{server_id}"))

    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel_admin"))

    await callback_query.message.edit_text(
        "Выберите сервер, который хотите удалить:",
        reply_markup=keyboard.adjust(1).as_markup()
    )

@router.callback_query(lambda c: c.data.startswith("select_delete_server_"))
async def confirm_delete_server(callback_query: types.CallbackQuery, state: FSMContext):
    """Подтверждение удаления сервера"""
    await callback_query.answer()
    server_id = int(callback_query.data.split("_")[-1])

    await state.update_data(server_id=server_id)

    keyboard = InlineKeyboardBuilder().add(
        InlineKeyboardButton(text=BUTTON_TEXTS["confirm_delete"], callback_data=f"server_confirm_{server_id}"),
        InlineKeyboardButton(text=BUTTON_TEXTS["cancel"],callback_data="cancel_admin")
    )

    await callback_query.message.edit_text(
        f"Вы уверены, что хотите удалить сервер с ID {server_id}?",
        reply_markup=keyboard.as_markup()
    )

@router.callback_query(lambda c: c.data.startswith("server_confirm"))
async def process_delete_server(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработка удаления выбранного сервера"""
    await callback_query.answer()

    server_id = int(callback_query.data.split("_")[-1])
    success = delete_server(server_id)
    if success:
        await callback_query.message.edit_text(f"✅ Сервер с ID {server_id} был успешно удалён.")
    else:
        await callback_query.message.edit_text(f"❌ Произошла ошибка при удалении сервера с ID {server_id}. Попробуйте снова.")
    await state.clear()


def is_valid_server_ids(server_ids: str) -> bool:
    """
    Проверяет, соответствует ли строка формату списка серверов.
    Формат: числа, разделенные запятыми (например, "1,2,3").
    """
    return bool(re.match(r"^\d+(,\d+)*$", server_ids))


@router.callback_query(lambda c: c.data.startswith("change_group_server"))
async def add_or_update_server_group(callback: types.CallbackQuery, state: FSMContext):
    """
    Запускает процесс добавления или обновления группы серверов.
    Запрашивает у пользователя номер главного сервера группы.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel_admin"))

    sent_message = await callback.message.answer(
        "Введите номер сервера, который отображается у вас при покупке (например, '1', '2', 'random'):",
        reply_markup=keyboard.as_markup()
    )
    await state.update_data(
        sent_message_id=sent_message.message_id,  # Сохраняем ID сообщения с запросом
        chat_id=callback.message.chat.id,
        previous_message_id=callback.message.message_id  # Сохраняем ID предыдущего сообщения (если нужно)
    )
    await state.set_state(ServerGroupForm.waiting_for_group_name)
    await callback.answer()


@router.message(ServerGroupForm.waiting_for_group_name)
async def process_group_name(message: types.Message, state: FSMContext):
    """
    Обрабатывает номер главного сервера группы.
    Запрашивает у пользователя список серверов для включения в группу.
    """
    user_data = await state.get_data()
    sent_message_id = user_data.get('sent_message_id')  # ID сообщения с запросом на ввод номера сервера
    chat_id = user_data.get('chat_id')

    if sent_message_id and chat_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=sent_message_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")

    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel_admin"))

    await state.update_data(group_name=message.text)
    sent_message = await message.answer(
        "Введите список ID серверов через запятую, которые будут включены в кластер (например, '1,3,5'):\n\n"
        "При выборе сервера бот будет сравнивать нагрузку на каждый сервер из этого списка. "
        "Например, если клиент выбрал сервер '1', бот проверит, сколько клиентов сейчас на серверах 1, 2 и 3, "
        "и создаст подписку на наименее загруженном сервере.",
        reply_markup=keyboard.as_markup()
    )
    await state.update_data(
        sent_message_id=sent_message.message_id,  # Сохраняем ID нового сообщения
        previous_message_id=message.message_id  # Сохраняем ID текущего сообщения для удаления
    )
    await state.set_state(ServerGroupForm.waiting_for_server_ids)


@router.message(ServerGroupForm.waiting_for_server_ids)
async def process_server(message: types.Message, state: FSMContext):
    """
    Обрабатывает ввод списка серверов.
    Добавляет или обновляет группу серверов в базе данных.
    """
    user_data = await state.get_data()
    group_name = user_data["group_name"]
    server_ids = message.text
    sent_message_id = user_data.get('sent_message_id')
    chat_id = user_data.get('chat_id')
    previous_message_id = user_data.get('previous_message_id')
    if sent_message_id and chat_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=sent_message_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")

    if not is_valid_server_ids(server_ids):
        await message.answer(
            "❌ Некорректный формат списка серверов. "
            "Введите ID серверов через запятую (например, '1,3,5')."
        )
        return

    try:
        connection = sqlite3.connect(SERVEDATABASE)
        cursor = connection.cursor()

        cursor.execute(
            "INSERT OR REPLACE INTO server_groups (group_name, server_ids) VALUES (?, ?)",
            (group_name, server_ids),
        )
        connection.commit()

        await message.answer(
            f"✅ Группа серверов '{group_name}' успешно добавлена или обновлена.\n\n"
            f"Список серверов: {server_ids}"
        )
    except Exception as e:
        if sent_message_id and chat_id:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message_id,
                text=f"❌ Ошибка при добавлении/обновлении группы серверов: {e}"
            )
        else:
            await message.answer(
                f"❌ Ошибка при добавлении/обновлении группы серверов: {e}"
            )
    finally:
        connection.close()
        await state.clear()
        