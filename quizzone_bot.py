# QuizZone - Rubika quiz & mini-games bot
# Python 3.10+
# Required: requests
# Set environment variable RUBIKA_BOT_TOKEN (never publish your token).

import os
import time
import json
import random
import sqlite3
import logging
from datetime import datetime

import requests

TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "FBFGE0XMDLMYHCTYFQEQLCBBQGWSWPOMDDOWGQCJZYMJMAMVMGRFASEZLTEDYBZC").strip()
if not TOKEN:
    raise RuntimeError("Set RUBIKA_BOT_TOKEN in your environment.")

API = f"https://botapi.rubika.ir/v3/{TOKEN}"
DB_FILE = os.getenv("QUIZZONE_DB", "quizzone.sqlite3")
POLL_DELAY = 2
TIMEOUT = 25

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
session = requests.Session()

# ---------- Rubika API ----------
def api(method, payload=None):
    response = session.post(API + "/" + method, json=payload or {}, timeout=TIMEOUT)
    response.raise_for_status()
    body = response.json()
    if isinstance(body, dict) and body.get("status") not in (None, "OK"):
        raise RuntimeError(f"Rubika API: {body.get('status_det') or body.get('status')}")
    return body.get("data", body) if isinstance(body, dict) else body

def send(chat_id, text):
    api("sendMessage", {"chat_id": str(chat_id), "text": text})

# ---------- Database ----------
db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("""
CREATE TABLE IF NOT EXISTS users(
  chat_id TEXT PRIMARY KEY,
  points INTEGER NOT NULL DEFAULT 0,
  games INTEGER NOT NULL DEFAULT 0,
  wins INTEGER NOT NULL DEFAULT 0,
  best_streak INTEGER NOT NULL DEFAULT 0,
  streak INTEGER NOT NULL DEFAULT 0,
  last_seen TEXT
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS states(
  chat_id TEXT PRIMARY KEY,
  state_json TEXT NOT NULL
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS processed_updates(
  update_key TEXT PRIMARY KEY,
  processed_at REAL NOT NULL
)
""")
db.commit()

def ensure_user(chat_id):
    db.execute("INSERT OR IGNORE INTO users(chat_id) VALUES(?)", (str(chat_id),))
    db.execute("UPDATE users SET last_seen=? WHERE chat_id=?", (datetime.now().isoformat(timespec="seconds"), str(chat_id)))
    db.commit()

def get_user(chat_id):
    ensure_user(chat_id)
    return db.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),)).fetchone()

def add_points(chat_id, points, win=False):
    ensure_user(chat_id)
    row = get_user(chat_id)
    streak = row["streak"] + 1 if win else 0
    db.execute("""
      UPDATE users SET points=MAX(0, points+?), games=games+1, wins=wins+?,
      streak=?, best_streak=MAX(best_streak, ?)
      WHERE chat_id=?
    """, (points, 1 if win else 0, streak, streak, str(chat_id)))
    db.commit()

def set_state(chat_id, state):
    db.execute("INSERT OR REPLACE INTO states(chat_id,state_json) VALUES(?,?)",
               (str(chat_id), json.dumps(state, ensure_ascii=False)))
    db.commit()

def get_state(chat_id):
    row = db.execute("SELECT state_json FROM states WHERE chat_id=?", (str(chat_id),)).fetchone()
    if not row:
        return None
    try:
        state = json.loads(row["state_json"])
        if state.get("expires", 0) < time.time():
            clear_state(chat_id)
            return None
        return state
    except Exception:
        clear_state(chat_id)
        return None

def clear_state(chat_id):
    db.execute("DELETE FROM states WHERE chat_id=?", (str(chat_id),))
    db.commit()

# ---------- Content ----------
QUIZ = [
    ("جغرافیا", "پایتخت ژاپن کدام است؟", ["توکیو", "سئول", "پکن", "بانکوک"], 0),
    ("علوم", "کدام سیاره به سیاره سرخ معروف است؟", ["زهره", "مریخ", "مشتری", "عطارد"], 1),
    ("تاریخ", "خط هیروگلیف بیشتر با کدام تمدن شناخته می‌شود؟", ["روم", "مصر باستان", "مایا", "چین"], 1),
    ("تکنولوژی", "HTML برای چه کاری استفاده می‌شود؟", ["ساختار صفحه وب", "مدیریت پایگاه داده", "سیستم‌عامل", "ویرایش ویدیو"], 0),
    ("عمومی", "بزرگ‌ترین اقیانوس زمین کدام است؟", ["اطلس", "هند", "آرام", "منجمد شمالی"], 2),
    ("علوم", "نماد شیمیایی اکسیژن چیست؟", ["Ox", "O", "Og", "X"], 1),
    ("جغرافیا", "کدام کشور به شکل چکمه معروف است؟", ["اسپانیا", "ایتالیا", "یونان", "پرتغال"], 1),
    ("تکنولوژی", "کدام زبان معمولاً برای تعامل در صفحات وب استفاده می‌شود؟", ["JavaScript", "SQL", "C", "Bash"], 0),
    ("عمومی", "یک هفته چند ساعت است؟", ["۱۴۴", "۱۶۸", "۱۸۰", "۱۲۰"], 1),
    ("علوم", "نیروی جاذبه باعث چه می‌شود؟", ["دور شدن اجسام", "جذب اجسام دارای جرم", "تولید نور", "توقف زمان"], 1),
    ("تاریخ", "اهرام مشهور جیزه در کدام کشور هستند؟", ["مصر", "ترکیه", "ایران", "هند"], 0),
    ("جغرافیا", "کدام قاره کوچک‌ترین قاره از نظر مساحت است؟", ["اروپا", "آفریقا", "استرالیا", "آمریکای جنوبی"], 2),
]

WORDS = ["کامپیوتر", "باران", "کتابخانه", "دریا", "سیاره", "پنجره", "برنامه", "پرنده", "مدرسه", "فناوری"]
SEQUENCES = [
    ("۳، ۶، ۹، ۱۲، ؟", "۱۵", "هر بار ۳ تا اضافه می‌شود."),
    ("۱، ۲، ۴، ۸، ؟", "۱۶", "هر بار عدد دو برابر می‌شود."),
    ("۲، ۵، ۱۰، ۱۷، ؟", "۲۶", "به ترتیب ۳، ۵، ۷ و ۹ اضافه می‌شود."),
    ("۱، ۱، ۲، ۳، ۵، ؟", "۸", "هر عدد حاصل جمع دو عدد قبلی است."),
    ("۱۰، ۲۰، ۳۰، ؟", "۴۰", "هر بار ۱۰ تا اضافه می‌شود."),
]
RIDDLES = [
    ("چه چیزی هرچه بیشتر از آن برداری، بزرگ‌تر می‌شود؟", "گودال"),
    ("چه چیزی دندان دارد اما غذا نمی‌خورد؟", "شانه"),
    ("چه چیزی پر از سوراخ است ولی آب را نگه می‌دارد؟", "اسفنج"),
    ("چه چیزی همیشه جلو می‌رود و برنمی‌گردد؟", "زمان"),
    ("چه چیزی کلید دارد ولی قفل باز نمی‌کند؟", "پیانو"),
]

HELP = """🎮 به QuizZone خوش آمدی!

🎯 بازی‌ها:
• چالش — سؤال چهارگزینه‌ای
• مسابقه — ۵ سؤال پشت‌سرهم
• حدس عدد — عددی بین ۱ تا ۳۰
• حدس کلمه — کشف کلمه مخفی
• سرعت — محاسبه سریع
• دنباله — پیدا کردن عدد بعدی
• معما — حل معمای کوتاه

📈 امکانات:
• پروفایل — آمار و سطح
• جدول — ۱۰ بازیکن برتر
• لغو — پایان بازی فعلی

پاسخ سؤال‌های چهارگزینه‌ای را با شماره گزینه (۱ تا ۴) بفرست.
"""

def normalize(s):
    return s.strip().lower().replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace(" ", "")

def menu_text():
    return "🎮 QuizZone\n\nبرای شروع یکی از این‌ها را بنویس:\nچالش | مسابقه | حدس عدد | حدس کلمه | سرعت | دنباله | معما\n\nبرای راهنما: راهنما"

def start_quiz(chat_id, tournament=False):
    q = random.choice(QUIZ)
    state = {"game":"quiz", "question":q, "tournament":tournament,
             "remaining":4 if tournament else 0, "expires":time.time()+45}
    set_state(chat_id, state)
    cat, question, options, answer = q
    txt = f"🧠 {cat} | {'مسابقه' if tournament else 'چالش'}\n\n{question}\n\n"
    txt += "\n".join(f"{i+1}) {opt}" for i, opt in enumerate(options))
    txt += "\n\n⏳ ۴۵ ثانیه فرصت داری. فقط شماره گزینه را بفرست."
    send(chat_id, txt)

def start_guess(chat_id):
    number = random.randint(1, 30)
    set_state(chat_id, {"game":"number", "target":number, "tries":7, "expires":time.time()+180})
    send(chat_id, "🔢 بازی حدس عدد شروع شد!\nیک عدد بین ۱ تا ۳۰ حدس بزن.\n۷ فرصت داری. برای لغو بنویس «لغو».")

def start_word(chat_id):
    word = random.choice(WORDS)
    masked = " ".join("＿" for _ in word)
    set_state(chat_id, {"game":"word", "word":word, "tries":6, "revealed":[], "expires":time.time()+180})
    send(chat_id, f"🔤 حدس کلمه!\nموضوع: کلمه‌های عمومی\n\n{masked}\n\nکلمه را حدس بزن. ۶ تلاش داری.")

def start_speed(chat_id):
    a, b = random.randint(3, 15), random.randint(3, 12)
    op = random.choice(["+", "-", "×"])
    ans = a+b if op=="+" else a-b if op=="-" else a*b
    set_state(chat_id, {"game":"speed", "answer":str(ans), "expires":time.time()+20})
    send(chat_id, f"⚡ چالش سرعت!\n\n{a} {op} {b} = ؟\n\n۲۰ ثانیه فرصت داری!")

def start_sequence(chat_id):
    seq, ans, hint = random.choice(SEQUENCES)
    set_state(chat_id, {"game":"sequence", "answer":ans, "hint":hint, "expires":time.time()+60})
    send(chat_id, f"🧩 دنباله را کامل کن:\n\n{seq}\n\n۶۰ ثانیه فرصت داری.")

def start_riddle(chat_id):
    riddle, answer = random.choice(RIDDLES)
    set_state(chat_id, {"game":"riddle", "answer":answer, "expires":time.time()+120})
    send(chat_id, f"🕵️ معما:\n\n{riddle}\n\n۲ دقیقه فرصت داری.")

def profile(chat_id):
    u = get_user(chat_id)
    level = u["points"] // 100 + 1
    win_rate = (u["wins"] * 100 // u["games"]) if u["games"] else 0
    send(chat_id, f"👤 پروفایل بازی\n\n🏆 امتیاز: {u['points']}\n⭐ سطح: {level}\n🎮 بازی‌ها: {u['games']}\n✅ برد: {u['wins']}\n📊 درصد برد: {win_rate}%\n🔥 بردهای متوالی: {u['streak']}\n🏅 بهترین زنجیره: {u['best_streak']}")

def leaderboard(chat_id):
    rows = db.execute("SELECT chat_id, points, wins FROM users ORDER BY points DESC, wins DESC LIMIT 10").fetchall()
    if not rows:
        send(chat_id, "هنوز بازیکنی ثبت نشده.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 جدول برترین بازیکنان\n"]
    for i, row in enumerate(rows, 1):
        mark = medals[i-1] if i <= 3 else f"{i}."
        # IDs are deliberately not exposed; display anonymous player numbers.
        lines.append(f"{mark} بازیکن {i} — {row['points']} امتیاز | {row['wins']} برد")
    send(chat_id, "\n".join(lines))

def quiz_answer(chat_id, state, text):
    q = state["question"]
    answer = q[3]
    try:
        choice = int(text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))) - 1
    except ValueError:
        send(chat_id, "فقط شماره گزینه (۱ تا ۴) را ارسال کن.")
        return
    if choice not in range(4):
        send(chat_id, "گزینه باید بین ۱ تا ۴ باشد.")
        return
    if choice == answer:
        points = 15
        add_points(chat_id, points, win=True)
        send(chat_id, f"✅ درست گفتی! +{points} امتیاز\n\nجواب: {q[2][answer]}")
    else:
        add_points(chat_id, 0, win=False)
        send(chat_id, f"❌ پاسخ درست: {q[2][answer]}")
    if state.get("tournament") and state.get("remaining", 0) > 0:
        state["remaining"] -= 1
        if state["remaining"] > 0:
            start_quiz(chat_id, tournament=True)
            # start_quiz initializes remaining; preserve tournament progress below
            new_state = get_state(chat_id)
            new_state["remaining"] = state["remaining"]
            set_state(chat_id, new_state)
            return
        clear_state(chat_id)
        send(chat_id, "🏁 مسابقه ۵ مرحله‌ای تمام شد! برای دیدن امتیازت «پروفایل» را بفرست.")
    else:
        clear_state(chat_id)
        send(chat_id, "🎮 بازی دیگری؟ نام بازی را ارسال کن.")

def handle_game(chat_id, text, state):
    game = state["game"]
    if game == "quiz":
        quiz_answer(chat_id, state, text)
        return
    if game == "number":
        try:
            n = int(text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
        except ValueError:
            send(chat_id, "یک عدد بین ۱ تا ۳۰ وارد کن.")
            return
        if not 1 <= n <= 30:
            send(chat_id, "عدد باید بین ۱ تا ۳۰ باشد.")
            return
        state["tries"] -= 1
        if n == state["target"]:
            pts = 25 + state["tries"] * 3
            add_points(chat_id, pts, win=True)
            clear_state(chat_id)
            send(chat_id, f"🎉 درست حدس زدی! عدد {n} بود.\n🏆 +{pts} امتیاز")
        elif state["tries"] <= 0:
            add_points(chat_id, 0, win=False)
            clear_state(chat_id)
            send(chat_id, f"فرصت‌ها تمام شد! عدد {state['target']} بود.")
        else:
            hint = "بزرگ‌تره ⬆️" if n < state["target"] else "کوچک‌تره ⬇️"
            set_state(chat_id, state)
            send(chat_id, f"{hint}\nفرصت باقی‌مانده: {state['tries']}")
        return
    if game == "word":
        guess = normalize(text)
        word = normalize(state["word"])
        if guess == word:
            pts = 30 + state["tries"] * 2
            add_points(chat_id, pts, win=True)
            clear_state(chat_id)
            send(chat_id, f"🎉 آفرین! کلمه «{state['word']}» بود.\n+{pts} امتیاز")
        else:
            state["tries"] -= 1
            if state["tries"] <= 0:
                add_points(chat_id, 0, win=False)
                clear_state(chat_id)
                send(chat_id, f"❌ تمام شد! کلمه: {state['word']}")
            else:
                set_state(chat_id, state)
                send(chat_id, f"❌ این کلمه نیست. {state['tries']} تلاش باقی مانده.")
        return
    if game in ("speed", "sequence", "riddle"):
        answer = normalize(text)
        expected = normalize(state["answer"])
        # Permit Persian/Arabic digits in numerical answers
        answer = answer.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        expected = expected.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        if answer == expected:
            pts = {"speed":20, "sequence":20, "riddle":25}[game]
            add_points(chat_id, pts, win=True)
            clear_state(chat_id)
            send(chat_id, f"✅ جواب درست! +{pts} امتیاز")
        else:
            if game == "sequence":
                send(chat_id, "❌ جواب درست نیست. راهنمایی: " + state["hint"])
            else:
                send(chat_id, "❌ جواب درست نیست، یک بار دیگر امتحان کن.")
        return

def process_message(update):
    chat_id = update.get("chat_id")
    message = update.get("new_message") or {}
    if not chat_id or not isinstance(message, dict):
        return

    # Ignore bot-originated updates and deduplicate retries from the API.
    if str(message.get("sender_type", "")).lower() == "bot":
        return
    update_key = str(update.get("update_id") or message.get("message_id") or "")
    if update_key:
        already = db.execute("SELECT 1 FROM processed_updates WHERE update_key=?", (update_key,)).fetchone()
        if already:
            return
        db.execute("INSERT OR IGNORE INTO processed_updates(update_key,processed_at) VALUES(?,?)", (update_key, time.time()))
        db.commit()

    text = (message.get("text") or "").strip()
    if not text:
        return
    ensure_user(chat_id)
    lower = normalize(text)

    if lower in ("لغو", "cancel", "/cancel"):
        clear_state(chat_id)
        send(chat_id, "بازی فعلی لغو شد. برای بازی جدید، نام بازی را بفرست.")
        return
    if lower in ("/start", "شروع", "سلام", "منو", "menu"):
        clear_state(chat_id)
        send(chat_id, menu_text())
        return
    if lower in ("/help", "راهنما", "کمک"):
        send(chat_id, HELP)
        return
    if lower in ("پروفایل", "آمار", "profile"):
        profile(chat_id)
        return
    if lower in ("جدول", "رتبه", "برترین", "leaderboard"):
        leaderboard(chat_id)
        return
    if lower in ("چالش", "سوال", "سؤال", "quiz"):
        start_quiz(chat_id)
        return
    if lower in ("مسابقه", " tournament", "تور", "competition"):
        start_quiz(chat_id, tournament=True)
        return
    if lower in ("حدسعدد", "حدس عدد", "number"):
        start_guess(chat_id)
        return
    if lower in ("حدسکلمه", "حدس کلمه", "word"):
        start_word(chat_id)
        return
    if lower in ("سرعت", "چالشسرعت", "speed"):
        start_speed(chat_id)
        return
    if lower in ("دنباله", "اعداد", "sequence"):
        start_sequence(chat_id)
        return
    if lower in ("معما", "چیستان", "riddle"):
        start_riddle(chat_id)
        return

    state = get_state(chat_id)
    if state:
        handle_game(chat_id, text, state)
    else:
        # Unknown messages outside a game are intentionally ignored to prevent spam.
        return

def run():
    offset_id = None
    logging.info("QuizZone started.")
    while True:
        try:
            payload = {"limit": 10}
            if offset_id:
                payload["offset_id"] = offset_id
            result = api("getUpdates", payload)
            updates = result.get("updates", []) if isinstance(result, dict) else []
            for update in updates:
                try:
                    if isinstance(update, dict):
                        process_message(update)
                except Exception:
                    logging.exception("Failed to process update")
            next_offset = result.get("next_offset_id") if isinstance(result, dict) else None
            if next_offset:
                offset_id = str(next_offset)
            elif updates:
                # Fallback: use the last update's ID if the API omits next_offset_id.
                last_update = updates[-1] if isinstance(updates[-1], dict) else {}
                fallback_id = last_update.get("update_id") or last_update.get("message_id")
                if fallback_id:
                    offset_id = str(fallback_id)
            time.sleep(POLL_DELAY)
        except requests.RequestException:
            logging.exception("Network/API error")
            time.sleep(5)
        except Exception:
            logging.exception("Unexpected polling error")
            time.sleep(5)

if __name__ == "__main__":
    run()

