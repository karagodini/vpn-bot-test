
import sqlite3
from dotenv import load_dotenv
import os
load_dotenv()

USERSDATABASE = os.getenv("USERSDATABASE")

async def log_promo_code_usage(telegram_id, user_promo_code):
    """
    Функция логирования использования промокода

    Эта асинхронная функция проверяет, использовал ли пользователь промокод ранее,  
    и, если нет, помечает его как использованный в базе данных.
    """
    try:
        conn = sqlite3.connect(USERSDATABASE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, promo_code_usage
            FROM users
            WHERE telegram_id = ?
        """, (telegram_id,))
        user_data = cursor.fetchone()

        if not user_data:
            return "❌ User not found."

        user_id, promo_code_usage = user_data
        if promo_code_usage > 0:
            return "❌ Promo code has already been used by this user."
        cursor.execute("""
            UPDATE users
            SET promo_code_usage = 1
            WHERE id = ?
        """, (user_id,))
        conn.commit()
        return "✅ Promo code usage successfully logged and marked as used."
    except sqlite3.Error as e:
        return f"❌ Database error: {e}"
    finally:
        cursor.close()
        conn.close()
