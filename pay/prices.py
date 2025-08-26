"""
📌 Описание модуля

В этом модуле вы задаете настройки подписок, включая:  
- Стоимость подписки для разных периодов.  
- Длительность подписок (в днях).  
- Названия кнопок выбора подписки.  
- Процент скидки (по реферальной программе и промокодам).  
- Ограничения по трафику (если применимо).  

📌 Константы:
- `BASE_PRICES` – базовые цены подписок.  
- `total_gb_values` – лимиты по трафику (если применимо).  

"""

from aiogram import types
import sqlite3
from aiogram.utils.keyboard import InlineKeyboardBuilder
from log import logger
from buttons.client import BUTTON_TEXTS
from dotenv import load_dotenv
from aiogram.types import CallbackQuery
import os

load_dotenv()
USERSDATABASE = os.getenv("USERSDATABASE")
# Количество дней в подписке, на выбранную дату, пробный, 1 месяц, 3, 6, 12
TRIAL = 3
ONE_M = 30
THREE_M = 93
ONE_YEAR = 365

# Ограничение по трафику, если нужно, в зависимости от выбранного периода, 0 = безлимит.
total_gb_values = {
    TRIAL: 0,    # на 3 дня
    ONE_M: 0,    # 1 месяц
    THREE_M: 0,  # 3 месяца
    ONE_YEAR: 0, # На год
}
# Базовые цены на подписку, в рублях
BASE_PRICES = {
    TRIAL: 0,   
    ONE_M: 80,    # 1 месяц - 81 рублей
    THREE_M: 200,  # 3 месяца - 200 рублей
    ONE_YEAR: 750 # 1 год - 800 рублей
}
# То как будет писаться период в сводной инвормации, при покупке.
def get_expiry_time_description(expiry_time):
    """
    Возвращает текстовое описание срока подписки.
    """
    descriptions = {
        ONE_M: "30 дней",
        THREE_M: "90 дней",
        ONE_YEAR: "365 дней"
    }
    return descriptions.get(expiry_time, "бесплатный период")

# Расчет скидки пользователя, складывает скидку за количество рефералов и введенный промокод, если такой имеется.
def get_price_with_referral_info(expiry_time_ms, telegram_id, promo_code=None):
    """
    Рассчитывает стоимость подписки с учетом скидки за рефералов и промокод.
    """
    referral_count = get_referral_count(telegram_id)

    if referral_count >= 10: #Если 10 и более
        referral_discount = 0.4  # 40%
    elif referral_count >= 5:#Если 5 и более
        referral_discount = 0.15  # 15%
    elif referral_count >= 1: #Если 1 и более
        referral_discount = 0.05  # 5%
    else:
        referral_discount = 0.0  # Без скидки
    promo_discount = 0

    if promo_code:
        conn_users = sqlite3.connect(USERSDATABASE)
        cursor_users = conn_users.cursor()
        cursor_users.execute(""" 
            SELECT promo_code_usage 
            FROM users
            WHERE telegram_id = ?
        """, (telegram_id,))
        promo_usage_data = cursor_users.fetchone()

        if promo_usage_data and promo_usage_data[0] == 1:
            cursor_users.close()
            conn_users.close()
            return str(int(BASE_PRICES.get(expiry_time_ms, 0) * (1 - referral_discount))), f"{int(referral_discount * 100)}", referral_count
        cursor_users.execute("""
            SELECT COUNT(*) 
            FROM used_promo_codes 
            WHERE user_id = ? AND promo_code = ?
        """, (telegram_id, promo_code))
        used_count = cursor_users.fetchone()[0]

        if used_count > 0:
            cursor_users.close()
            conn_users.close()
            return str(int(BASE_PRICES.get(expiry_time_ms, 0) * (1 - referral_discount))), f"{int(referral_discount * 100)}", referral_count
        cursor_users.execute("""
            SELECT discount
            FROM promo_codes
            WHERE code = ? AND is_active = 1
        """, (promo_code,))
        promo_data = cursor_users.fetchone()

        if promo_data:
            promo_discount = promo_data[0] / 100

        cursor_users.close()
        conn_users.close()
    total_discount = referral_discount + promo_discount
    if total_discount > 0.8:# Ограничение макисмальной скидки, не больше 80%
        total_discount = 0.8
    base_price = BASE_PRICES.get(expiry_time_ms, 1)
    
    if base_price == 0:
        return 0, "❌ Ошибка в расчетах. Пожалуйста, попробуйте снова.", referral_count
    
    final_price = int(base_price * (1 - total_discount))
    discount_percentage = int(total_discount * 100)
    if discount_percentage == 0:
        discount_percentage = "0"
    return str(final_price), f"{discount_percentage}", referral_count

#Клавиатура выбора срока подписки при покупке
def get_expiry_time_keyboard(callback_query: types.CallbackQuery):
    """
    Создает клавиатуру для выбора срока подписки.
    """
    telegram_id = callback_query.from_user.id 
    logger.info(f"DEBUG: Получен telegram_id {telegram_id} из callback_query")
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["one_m"], callback_data=str(ONE_M))
    )
    keyboard.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["three_m"], callback_data=str(THREE_M))
    )
    keyboard.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["twelve_m"], callback_data=str(ONE_YEAR))
    )
    keyboard.add(types.InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="main_menu"))
    return keyboard.adjust(1).as_markup()


def get_test_menu():
    """
    Создает меню для приобретения подписки.
    """
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["one_m"], callback_data="one_m_menu"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["three_m"], callback_data="main_menu"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["twelve_m"], callback_data="main_menu"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return builder.adjust(1).as_markup()

def get_subscription_one():
    """
    Создает меню для приобретения подписки.
    """
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="one_m_device")
    )
    return builder.adjust(1).as_markup()
    
def get_subscription_one_device():
    """
    Создает меню для выбора устройства.
    """
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["ios"], callback_data="one_m_ios"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["android"], callback_data="one_m_android")
    )
    builder.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["macos"], callback_data="one_m_macos"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["windows"], callback_data="one_m_windows")
    )
    return builder.adjust(2).as_markup()

def get_subscription_one_ios():
    """
    Создает меню для выбора устройства.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text="Установить1", url="https://apps.apple.com/app/id6476628951"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="confirm_expiry_time"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return keyboard.adjust(1).as_markup()

def get_subscription_one_android():
    """
    Создает меню для выбора устройства.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text="Установить", url="https://play.google.com/store/apps/details?id=com.v2raytun.android&pli=1"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="confirm_expiry_time"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return keyboard.adjust(1).as_markup()

def get_subscription_one_macos():
    """
    Создает меню для выбора устройства.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text="Установить", url="https://apps.apple.com/app/id6476628951"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="confirm_expiry_time"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return keyboard.adjust(1).as_markup()

def get_subscription_one_windows():
    """
    Создает меню для выбора устройства.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text="Установить", url="https://github.com/KaringX/karing/releases/tag/v1.1.2.606"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="confirm_expiry_time"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return keyboard.adjust(1).as_markup()

"""меню для пробной подписки"""
def get_trial_device():
    """
    Создает меню для выбора устройства.
    """
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["ios"], callback_data="trial_ios"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["android"], callback_data="trial_android")
    )
    builder.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["macos"], callback_data="trial_macos"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["windows"], callback_data="trial_windows")
    )
    return builder.adjust(2).as_markup()

def get_trial_ios():
    """
    Создает меню для выбора устройства.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text="Установить2", url="https://apps.apple.com/app/id6476628951"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="trial_1"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return keyboard.adjust(1).as_markup()

def get_trial_android():
    """
    Создает меню для выбора устройства.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text="Установить", url="https://play.google.com/store/apps/details?id=com.v2raytun.android&pli=1"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="trial_1"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return keyboard.adjust(1).as_markup()

def get_trial_macos():
    """
    Создает меню для выбора устройства.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text="Установить", url="https://apps.apple.com/app/id6476628951"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="trial_1"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return keyboard.adjust(1).as_markup()

def get_trial_windows():
    """
    Создает меню для выбора устройства.
    """
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text="Установить", url="https://github.com/KaringX/karing/releases/tag/v1.1.2.606"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="trial_1"),
        types.InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
    )
    return keyboard.adjust(1).as_markup()

"""end меню для пробной подписки"""

def get_referral_count(telegram_id):
    """
    Получает количество рефералов пользователя.
    """
    conn = sqlite3.connect(USERSDATABASE)
    cursor = conn.cursor() 
    cursor.execute("SELECT referral_count FROM users WHERE telegram_id = ?", (telegram_id,))
    referral_count = cursor.fetchone()
    cursor.close()
    conn.close()
    if referral_count:
        return referral_count[0]
    else:
        return 0
    
    
#Показывать или нет кнопку с пробной подпиской    
def has_active_subscription(telegram_id):
    """
    Проверяет, есть ли у пользователя активная пробная подписка.
    """
    conn = sqlite3.connect(USERSDATABASE)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT has_trial FROM users WHERE telegram_id = ?
    ''', (telegram_id,))

    result = cursor.fetchone()
    
    cursor.close()
    conn.close()

    return result is not None and result[0] == 1

def should_show_prodlit_button(telegram_id):
    """
    Проверяет, нужно ли показывать кнопку 'Продлить' вместо 'Купить VPN'.
    Возвращает True если has_trial или sum_my не равны 0.
    """
    conn = sqlite3.connect(USERSDATABASE)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT has_trial, sum_my FROM users WHERE telegram_id = ?
    ''', (telegram_id,))

    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if result is None:
        return False

    has_trial, sum_my = result
    return has_trial != 0 or sum_my != 0