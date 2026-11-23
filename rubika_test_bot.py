import os
import time
import threading
import logging

import requests
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

TOKEN = os.environ.get("RUBIKA_BOT_TOKEN", "CJGAJC0DBPYNSYQWYZNRHOQRWIBJCIRXYEWKWFSHFWIRSXYBYFZBKXRXXGCBZQQG").strip()
if not TOKEN:
    raise RuntimeError("RUBIKA_BOT_TOKEN environment variable is missing.")

API_BASE = f"https://botapi.rubika.ir/v3/{TOKEN}"
HTTP = requests.Session()
POLL_DELAY = 2

app = Flask(__name__)
poller_started = False
poller_lock = threading.Lock()


def api_call(method, payload=None):
    response = HTTP.post(
        f"{API_BASE}/{method}",
        json=payload or {},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("status") not in (None, "OK"):
        raise RuntimeError(f"Rubika API returned status: {body.get('status')}")
    data = body.get("data", body)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected API response structure.")
    return data


def send_text(chat_id, text):
    api_call("sendMessage", {"chat_id": str(chat_id), "text": text})


def handle_update(update):
    if not isinstance(update, dict):
        return
    chat_id = update.get("chat_id")
    if not chat_id:
        return

    msg = update.get("new_message") or {}
    if not isinstance(msg, dict):
        msg = {}

    # Ignore messages sent by the bot itself.
    if msg.get("sender_type") == "Bot":
        return

    text = (msg.get("text") or "").strip()
    event_type = update.get("type", "")

    if event_type == "StartedBot" or text == "/start":
        reply = "سلام! 👋 ربات آزمایشی روبیکا با موفقیت فعال شد.\nبرای راهنما /help را بفرست."
    elif text == "/help":
        reply = "دستورهای تست:\n/start — شروع\n/help — راهنما\nping — تست پاسخ"
    elif text.lower() == "ping":
        reply = "pong ✅"
    elif text == "سلام":
        reply = "سلام! پیام شما دریافت شد. ✅"
    else:
        reply = "پیامت دریافت شد؛ ربات آزمایشی در حال کار است. ✅"

    send_text(chat_id, reply)


def polling_loop():
    offset_id = None
    logging.info("Rubika test bot polling started.")
    while True:
        try:
            payload = {"limit": 10}
            if offset_id:
                payload["offset_id"] = offset_id

            data = api_call("getUpdates", payload)
            updates = data.get("updates", [])
            if isinstance(updates, list):
                for update in updates:
                    try:
                        handle_update(update)
                    except Exception:
                        logging.exception("Failed to handle one update.")

            next_offset = data.get("next_offset_id")
            if next_offset:
                offset_id = str(next_offset)

            time.sleep(POLL_DELAY)
        except Exception:
            logging.exception("Polling/API error; retrying shortly.")
            time.sleep(5)


@app.get("/")
def home():
    return "Rubika test bot is running.", 200


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "rubika-test-bot"}), 200


def start_poller_once():
    global poller_started
    with poller_lock:
        if poller_started:
            return
        thread = threading.Thread(target=polling_loop, daemon=True, name="rubika-poller")
        thread.start()
        poller_started = True


if __name__ == "__main__":
    start_poller_once()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
