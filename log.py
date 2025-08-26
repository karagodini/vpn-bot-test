import logging
import colorlog
from logging.handlers import RotatingFileHandler
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "bot.log")

def setup_logger():
    """Настройка логгера с цветными сообщениями в терминале и логами в файлах."""
    logger = logging.getLogger("bot")
    logger.setLevel(LOG_LEVEL)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = colorlog.ColoredFormatter(
        '%(asctime)s - %(log_color)s%(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'magenta',
        }
    )
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

logger = setup_logger()
