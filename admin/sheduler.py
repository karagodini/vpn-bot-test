from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers import SchedulerAlreadyRunningError
from apscheduler.triggers.interval import IntervalTrigger
from contextlib import suppress
from db.db import clean_referal_table

from admin.sub_check import (
    check_subscription_expiry,
    send_no_trial_broadcast,
    send_promo_not_used_broadcast,
    send_inactive_users_broadcast,
    check_all_user_subscriptions,
    update_all_days_left_on_startup
)
from admin.delete_clients import scheduled_delete_clients

from log import logger

scheduler = AsyncIOScheduler()

task_names = {
    "delete_clients": "Удаление подписок с истекшим временем",
    "check_subscription_expiry": "Рассылка о скором окончании подписки",
    "send_no_trial_broadcast": "Рассылка пользователям без пробного периода",
    "send_promo_not_used_broadcast": "Рассылка о неиспользованных промокодах",
    "send_inactive_users_broadcast": "Рассылка неактивным пользователям"
}

tasks = {
    "check_subscription_expiry": {
        "function": check_all_user_subscriptions,
        "hour": 4,
        "minute": 37,
        "enabled": True,
        "days": "*"
    },
    
    # НОВАЯ ЗАДАЧА: запускать проверку подписок КАЖДУЮ МИНУТУ
    #"check_subscription_expiry_interval": {
    #    "function": check_all_user_subscriptions,
    #    "interval_minutes": 1,
    #    "enabled": True
    #},
    
    # Остальные задачи без изменений
    "send_no_trial_broadcast": {
        "function": send_no_trial_broadcast,
        "hour": 5,
        "minute": 0,
        "enabled": True,
        "days": "mon,wed,fri"
    },
    "send_promo_not_used_broadcast": {
        "function": send_promo_not_used_broadcast,
        "hour": 5,
        "minute": 10,
        "enabled": True,
        "days": "sat,sun"
    },
    "send_inactive_users_broadcast": {
        "function": send_inactive_users_broadcast,
        "hour": 5,
        "minute": 20,
        "enabled": True,
        "days": "15"
    }
}

async def start_scheduler():
    logger.info("🕒 Инициализация планировщика...")

    for task_id, task in tasks.items():
        if not task["enabled"]:
            continue

        try:
            if "interval_minutes" in task:  # Для задач с интервальным выполнением
                trigger = IntervalTrigger(minutes=task["interval_minutes"])
                logger.info(f"✅ Задача: '{task_names.get(task_id, task_id)}' добавлена. Интервал: каждые {task['interval_minutes']} минут.")
            else:  # Для cron-задач
                days_config = parse_days(task["days"])
                trigger = CronTrigger(
                    hour=task.get("hour", "*"),  # Используем get() с значением по умолчанию
                    minute=task.get("minute", "*"),  # Используем get() с значением по умолчанию
                    **days_config
                )
                logger.info(f"✅ Задача: '{task_names.get(task_id, task_id)}' добавлена. Время: {task.get('hour', '*')}:{task.get('minute', '*'):02d}, Дни: {task['days']}.")
            
            scheduler.add_job(
                task["function"],
                trigger=trigger,
                id=task_id,
                name=task_names.get(task_id, task_id),
                replace_existing=True
            )
            
        except ValueError as e:
            logger.error(f"❌ Ошибка при добавлении задачи '{task_id}': {e}")
        except Exception as e:
            logger.error(f"❌ Непредвиденная ошибка при добавлении задачи '{task_id}': {e}")

    # Остальной код без изменений
    scheduler.add_job(
        clean_referal_table,
        CronTrigger(day=1, hour=0),
        id="clean_referal_table",
        name="Очистка таблицы рефералов",
        replace_existing=True
    )
    logger.info("✅ Задача очистки таблицы рефералов добавлена.")

    try:
        if not scheduler.running:
            scheduler.start()
            logger.info("🚀 Планировщик успешно запущен!")
        else:
            logger.info("⚠️ Планировщик уже работает.")
    except SchedulerAlreadyRunningError:
        logger.warning("⚠️ Попытка запустить уже запущенный планировщик.")
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске планировщика: {e}")

    try:
        logger.info("🔁 Запуск обновления days_left при старте бота...")
        await update_all_days_left_on_startup()
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении days_left при старте: {e}")


        
def parse_days(days_str):
    """
    Парсит строку дней и возвращает словарь, совместимый с CronTrigger.

    Возможные варианты:
    - "*" → каждый день
    - "mon,wed,fri" → только в понедельник, среду и пятницу
    - "1,15" → 1-го и 15-го числа месяца
    """
    valid_week_days = {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'}

    if days_str.strip() == "*":
        return {}

    parts = [part.strip().lower() for part in days_str.split(',')]

    if all(part in valid_week_days for part in parts):
        return {'day_of_week': ','.join(parts)}

    try:
        days = list(map(int, parts))
        if all(1 <= day <= 31 for day in days):
            return {'day': ','.join(map(str, days))}
    except ValueError:
        pass

    raise ValueError(f"Некорректный формат дней: {days_str}")

