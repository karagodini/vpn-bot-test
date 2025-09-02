from aiogram.enums.parse_mode import ParseMode
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from buttons.client import BUTTON_TEXTS
from aiogram import types
from pay.prices import has_active_subscription, should_show_prodlit_button 
from dotenv import load_dotenv
import os
from client.text import MENU_TEXT

load_dotenv()

SUPPORT = os.getenv("SUPPORT")


async def main_menu(message, edit=False, callback_query=None):
    """
    Обработка главного меню. Отправляет или редактирует сообщение с кнопками главного меню.
    """
    if callback_query is None:
        callback_query = message

    user = callback_query.from_user
    name = user.first_name or "друг"

    text = MENU_TEXT.format(name=name)

    if edit:
        await message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=get_main_menu(callback_query)
        )
    else:
        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=get_main_menu(callback_query)
        )



def get_back_button():
    """
    Создает кнопку для возвращения в главное меню.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu"))
    return keyboard.as_markup()

def get_instructions_button():
    """
    Создает кнопку для инструкций.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        InlineKeyboardButton(text="🍏 IOS", callback_data="show_instruction_ios"),
        InlineKeyboardButton(text="📱 Android", callback_data="show_instruction_android"),
        InlineKeyboardButton(text="💻 MacOS", callback_data="show_instruction_macos"),
        InlineKeyboardButton(text="🖥 Windows", callback_data="show_instruction_windows"),
    )
    keyboard.adjust(2)
    return keyboard.as_markup()

def get_button_not_sub():
    """
    Создает кнопку для покупки подписки.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["buy_vpn"], callback_data="buy_vpn"))
    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu"))
    return keyboard.as_markup()

def get_main_menu(callback_query: types.CallbackQuery):
    """
    Создает основное меню с кнопками для пользователя с учетом подписки.
    """
    telegram_id = callback_query.from_user.id
    builder = InlineKeyboardBuilder()

    # Проверяем условия для пробной подписки
    if not has_active_subscription(telegram_id):
        builder.add(types.InlineKeyboardButton(
            text=BUTTON_TEXTS["trial"], 
            callback_data="trial_go"
        ))

    # Основные кнопки
    builder.row(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["subscriptions"], 
            callback_data="extend_subscription"
        )
    )

    # Определяем какую кнопку показывать (Купить/Продлить)
    if should_show_prodlit_button(telegram_id):
        builder.row(
            InlineKeyboardButton(
                text=BUTTON_TEXTS["extend_subscription_subscr"], 
                callback_data="extend_subscription"
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=BUTTON_TEXTS["buy_vpn"], 
                callback_data="buy_vpn"
            )
        )

    # Остальные кнопки
    builder.row(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["sub"], 
            url="https://t.me/vpnmoy/"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["trial_seven"], 
            callback_data="trial_seven"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["support"], 
            url=SUPPORT
        ),
        InlineKeyboardButton(
            text=BUTTON_TEXTS["about_server"], 
            url="https://t.me/vpnmoy/12"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["referal"], 
            callback_data="referal"
        )
    )
    
    return builder.as_markup()

def get_cabinet_menu():
    """
    Создает меню для личного кабинета пользователя.
    """
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["promocode"], callback_data="enter_promo_code"),
        InlineKeyboardButton(text=BUTTON_TEXTS["subscriptions"], callback_data="cabinet"),
        InlineKeyboardButton(text=BUTTON_TEXTS["extend_subscription"], callback_data="extend_subscription"),
        InlineKeyboardButton(text=BUTTON_TEXTS["change_location"], callback_data="smena_servera"),
        InlineKeyboardButton(text=BUTTON_TEXTS["instructions"], callback_data="instructions"),
        InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return builder.adjust(1).as_markup()



def get_instructions_menu():
    """
    Создает меню для личного кабинета пользователя.
    """
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["ios"], callback_data="ios_instructions"),
        InlineKeyboardButton(text=BUTTON_TEXTS["android"], callback_data="android_instructions"),
        InlineKeyboardButton(text=BUTTON_TEXTS["macos"], callback_data="macos_instructions"),
        InlineKeyboardButton(text=BUTTON_TEXTS["windows"], callback_data="windows_instructions"),
        InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return builder.adjust(1).as_markup()

