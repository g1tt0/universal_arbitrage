import telebot
from time import sleep
from config import constants
import dotenv
import os
import re
from loguru import logger

dotenv.load_dotenv()


bot = telebot.TeleBot(token=os.environ.get("TELEGRAM_TOKEN"))


def send_message(message, parse_mode="Markdown", message_type=None):
    """
    Отправляет сообщение в заданный чат с использованием бота.

    :param message: Текст сообщения для отправки.
    :param parse_mode: Форматирование текста сообщения (по умолчанию Markdown).
    """
    if message_type == "swap":
        message = format_message_for_swap(message)

    chat_id = os.environ.get("CHAT_ID")
    max_attempts = 3
    sleep_time = 2  # Время ожидания перед повторной попыткой в секундах

    for attempt in range(max_attempts):
        try:
            bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            break
        except Exception as e:  # Замените на конкретное исключение
            logger.warning(f"Message: {message}")
            logger.error(f"Error occurred: {e}")
            sleep(sleep_time)


def format_message_for_swap(message):
    # Удаляем часть "Network: {network}. "
    message_without_network = re.sub(r"Network: .+?\. ", "", message)

    # Находим первое вхождение фигурных скобок и разделяем сообщение
    parts = re.split(r"(\{.+?\})", message_without_network, 1)

    # Если есть более одной части, добавляем '#' перед фигурными скобками во второй части
    if len(parts) > 1:
        parts[1] = re.sub(r"\{([^}]+)\}", r"#\{\1\}", parts[1])

    # Объединяем части обратно в одно сообщение
    message_with_hashes = "".join(parts)

    # Разделение сообщения на две части
    message_without_tx, tx_url = message_with_hashes.split("TX: ")

    # Замена "Swap" на "(Swap)[tx_url]" в первой части
    message_without_tx = message_without_tx.replace("Swap", f"[Swap]({tx_url.strip()})")

    # Возвращаем измененную первую часть
    final_message = message_without_tx.strip()

    return final_message


def format_message_for_swap(message):
    # Удаляем часть "Network: {network}. "
    message_without_network = re.sub(r"Network: .+?\. ", "", message)

    # Разделение сообщения на две части
    message_before_tx, tx_hash = message_without_network.split("TX: ")

    # Обрезка хеша транзакции до 8 символов
    tx_hash_short = tx_hash[-66:][:8]

    # Замена "Swap" на "(Swap)[tx_hash]" в первой части
    final_message = message_before_tx.replace("Swap", f"[Swap]({tx_hash})").strip()

    # Добавление обрезанного хеша транзакции обратно к сообщению
    final_message += f" TX: #{tx_hash_short}"

    return final_message
