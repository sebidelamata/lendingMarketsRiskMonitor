"""Telegram bot notification helpers (text messages and chart photos)."""

import requests

from .logging_setup import log


def send_telegram(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )

        resp.raise_for_status()

    except requests.RequestException as e:
        log.error("Failed to send Telegram message: %s", e)


def send_telegram_photo(bot_token, chat_id, photo_path, caption):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    try:
        with open(photo_path, "rb") as photo:
            resp = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "Markdown",
                },
                files={"photo": photo},
                timeout=30,
            )

        resp.raise_for_status()

    except (requests.RequestException, OSError) as e:
        log.error("Failed to send Telegram chart: %s", e)
