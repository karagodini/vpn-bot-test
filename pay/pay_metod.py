from dotenv import load_dotenv
import os
from buttons.client import BUTTON_TEXTS

"""
Конфигурация доступных методов оплаты.

Этот модуль загружает настройки платежных систем из переменных окружения и формирует
словарь `PAYMENT_METHODS`, содержащий информацию о доступных методах оплаты.

Каждый метод включает:
- `enabled` — активность метода (читается из `.env`).
- `text` — название кнопки для выбора метода.
- `callback_data` — данные для callback-запроса.
- `description` — описание метода оплаты для пользователя.

Поддерживаемые платежные системы:
- 💳 Юкасса (YooKassa)
- 💰 Робокасса (Robokassa)
- 💵 CryptoBot (оплата в криптовалюте)
- 💳 TGPAY (Telegram Payments)
- 🌟 Оплата звездами (Star)
- 💳 Cloudpayments
- 💳 Yoomoney
"""

ENABLE_YOOKASSA = os.getenv("ENABLE_YOOKASSA") == 'true'
ENABLE_ROBOKASSA = os.getenv("ENABLE_ROBOKASSA") == 'true'
ENABLE_CRYPTOBOT = os.getenv("ENABLE_CRYPTOBOT") == 'true'
ENABLE_TGPAY = os.getenv("ENABLE_TGPAY") == 'true'
ENABLE_STAR = os.getenv("ENABLE_STAR") == 'true'
ENABLE_CLOUDPAY = os.getenv("ENABLE_CLOUDPAY") == 'true'
ENABLE_YOOMONEY = os.getenv("ENABLE_YOOMONEY") == 'true'


PAYMENT_METHODS = {
    "yookassa": {
        "enabled": ENABLE_YOOKASSA,
        "text": BUTTON_TEXTS["yokassa"],
        "callback_data": "payment_method_yookassa",
        "description": "💳 <b>Юкасса:</b> Оплата банковскими картами и электронными кошельками."
    },
    "robokassa": {
        "enabled": ENABLE_ROBOKASSA,
        "text": BUTTON_TEXTS["robokassa"],
        "callback_data": "payment_method_robokassa",
        "description": "💰 <b>Робокасса:</b> Поддерживает популярные способы оплаты."
    },
    "cryptobot": {
        "enabled": ENABLE_CRYPTOBOT,
        "text": BUTTON_TEXTS["cryptobot"],
        "callback_data": "payment_method_cryptobot",
        "description": "💵 <b>CryptoBot:</b> Платежи в криптовалюте."
    },
    "tgpay": {
        "enabled": ENABLE_TGPAY,
        "text": BUTTON_TEXTS["tgpay"],
        "callback_data": "payment_method_tgpay",
        "description": "💳 <b>TGPAY:</b> Платежи напрямую через Telegram Payments."
    },
    "star": {
        "enabled": ENABLE_STAR,
        "text": BUTTON_TEXTS["star"],
        "callback_data": "payment_method_star",
        "description": "🌟 <b>Звезды:</b> Оплата звездами."
    },
    "cloudpay": {
        "enabled": ENABLE_CLOUDPAY,
        "text": BUTTON_TEXTS["cloudpay"],
        "callback_data": "payment_method_cloudpay",
        "description": "💳 <b>Cloudpayments:</b> Платежи в Cloudpayments."
    },
    "yoomoney": {
        "enabled": ENABLE_YOOMONEY,
        "text": BUTTON_TEXTS["yoomoney"],
        "callback_data": "payment_method_yoomoney",
        "description": "💳 <b>Yoomoney:</b> Переводы через Yoomoney."
    },
}
