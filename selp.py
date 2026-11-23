
import asyncio
import html
import json
import logging
import random
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

import spluspy


# =========================
# تنظیمات اصلی
# =========================

SESSION_NAME = "mohsen_selfbot"
CONFIG_FILE = Path("self_config.json")
TEHRAN = timezone(timedelta(hours=3, minutes=30))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DEFAULT_CONFIG = {
    "clock_enabled": False,
    "base_name": "Mohsen",
    "clock_font": "normal",
    "name_font": "normal",
    "random_clock": False,
    "random_name": False,
    "message_font_enabled": False,
    "message_font": "bold",
    "auto_reply": False,
    "reply_text": "سلام، پیام شما دریافت شد."
}

CLOCK_FONTS = {
    "normal": "0123456789",
    "bold": "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗",
    "double": "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡",
    "sans": "𝟢𝟣𝟤𝟥𝟦𝟧𝟨𝟩𝟪𝟫",
    "sans_bold": "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵",
    "monospace": "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿",
    "circled": "⓪①②③④⑤⑥⑦⑧⑨",
    "full": "０１２３４５６７８９",
    "sup": "⁰¹²³⁴⁵⁶⁷⁸⁹",
    "sub": "₀₁₂₃₄₅₆₇₈₉"
}

NAME_FONTS = [
    "normal",
    "bold",
    "italic",
    "bold_italic",
    "sans",
    "sans_bold",
    "script",
    "script_bold",
    "fraktur",
    "double",
    "monospace",
    "circled"
]

# حروف انگلیسی قابل تبدیل به سبک‌های یونیکد
LATIN_MAPS = {
    "bold": (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
        "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
    ),
    "italic": (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝐴𝐵𝐶𝐷𝐸𝐹𝐺𝐻𝐼𝐽𝐾𝐿𝑀𝑁𝑂𝑃𝑄𝑅𝑆𝑇𝑈𝑉𝑊𝑋𝑌𝑍"
        "𝑎𝑏𝑐𝑑𝑒𝑓𝑔ℎ𝑖𝑗𝑘𝑙𝑚𝑛𝑜𝑝𝑞𝑟𝑠𝑡𝑢𝑣𝑤𝑥𝑦𝑧"
    ),
    "bold_italic": (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝑨𝑩𝑪𝑫𝑬𝑭𝑮𝑯𝑰𝑱𝑲𝑳𝑴𝑵𝑶𝑷𝑸𝑹𝑺𝑻𝑼𝑽𝑾𝑿𝒀𝒁"
        "𝒂𝒃𝒄𝒅𝒆𝒇𝒈𝒉𝒊𝒋𝒌𝒍𝒎𝒏𝒐𝒑𝒒𝒓𝒔𝒕𝒖𝒗𝒘𝒙𝒚𝒛"
    ),
    "sans": (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝖠𝖡𝖢𝖣𝖤𝖥𝖦𝖧𝖨𝖩𝖪𝖫𝖬𝖭𝖮𝖯𝖰𝖱𝖲𝖳𝖴𝖵𝖶𝖷𝖸𝖹"
        "𝖺𝖻𝖼𝖽𝖾𝖿𝗀𝗁𝗂𝗃𝗄𝗅𝗆𝗇𝗈𝗉𝗊𝗋𝗌𝗍𝗎𝗏𝗐𝗑𝗒𝗓"
    ),
    "sans_bold": (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
        "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    ),
    "script": (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝒜ℬ𝒞𝒟ℰℱ𝒢ℋℐ𝒥𝒦ℒℳ𝒩𝒪𝒫𝒬ℛ𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵"
        "𝒶𝒷𝒸𝒹ℯ𝒻ℊℎ𝒾𝒿𝓀𝓁𝓂𝓃ℴ𝓅𝓆𝓇𝓈𝓉𝓊𝓋𝓌𝓍𝓎𝓏"
    ),
    "script_bold": (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝓐𝓑𝓒𝓓𝓔𝓕𝓖𝓗𝓘𝓙𝓚𝓛𝓜𝓝𝓞𝓟𝓠𝓡𝓢𝓣𝓤𝓥𝓦𝓧𝓨𝓩"
        "𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃"
    ),
    "fraktur": (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝔄𝔅ℭ𝔇𝔈𝔉𝔊ℌℑ𝔍𝔎𝔏𝔐𝔑𝔒𝔓𝔔𝔖𝔗𝔘𝔙𝔚𝔛𝔜𝔝"
        "𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷"
    ),
    "double": (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄𝕆𝕆𝕆𝕆𝕆𝕆𝕆𝕆𝕆𝕆𝕆𝕆𝕆𝕆𝕆𝕆"
        "𝕒𝕓𝕔𝕕𝕖𝕗𝕘𝕙𝕚𝕛𝕜𝕝𝕞𝕟𝕠𝕡𝕢𝕣𝕤𝕥𝕦𝕧𝕨𝕩𝕪𝕫"
    ),
    "monospace": (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉"
        "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣"
    )
}


# =========================
# ذخیره تنظیمات
# =========================

def save_config(data=None):
    if data is None:
        data = config

    CONFIG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf-8"
    )


def load_config():
    if not CONFIG_FILE.exists():
        result = DEFAULT_CONFIG.copy()
        save_config(result)
        return result

    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        result = DEFAULT_CONFIG.copy()

        if isinstance(saved, dict):
            result.update(saved)

        return result

    except Exception:
        logging.exception("خطا در خواندن تنظیمات")
        return DEFAULT_CONFIG.copy()


config = load_config()


def save():
    try:
        save_config(config)
    except Exception:
        logging.exception("خطا در ذخیره تنظیمات")


# =========================
# ابزار فونت
# =========================

def convert_digits(text, font_name):
    digits = CLOCK_FONTS.get(font_name, CLOCK_FONTS["normal"])
    return str(text).translate(str.maketrans("0123456789", digits))


def convert_latin(text, font_name):
    if font_name not in LATIN_MAPS:
        return text

    source, target = LATIN_MAPS[font_name]
    return str(text).translate(str.maketrans(source, target))


def convert_name(text, font_name):
    if font_name == "random":
        font_name = random.choice(NAME_FONTS)

    if font_name == "normal":
        return text

    return convert_latin(text, font_name)


# =========================
# قالب‌بندی واقعی پیام
# =========================

def format_html_message(text, style="bold"):
    safe_text = html.escape(str(text))

    tags = {
        "bold": ("<b>", "</b>"),
        "italic": ("<i>", "</i>"),
        "underline": ("<u>", "</u>"),
        "strike": ("<s>", "</s>")
    }

    if style not in tags:
        return safe_text

    opening, closing = tags[style]
    return opening + safe_text + closing


def protect_links(text):
    pattern = r"(https?://\S+|www\.\S+|@\w+)"
    return re.sub(pattern, lambda m: "\u2060" + m.group(0), text)


# =========================
# ساخت نام پروفایل
# =========================

def make_profile_name():
    now = datetime.now(TEHRAN)
    clock = now.strftime("%H:%M")

    clock_font = config.get("clock_font", "normal")
    name_font = config.get("name_font", "normal")

    if config.get("random_clock"):
        clock_font = random.choice(list(CLOCK_FONTS.keys()))

    if config.get("random_name"):
        name_font = random.choice(NAME_FONTS)

    clock = convert_digits(clock, clock_font)

    base_name = config.get("base_name", "Mohsen")
    base_name = convert_name(base_name, name_font)

    return f"{base_name} | {clock}"


# =========================
# اتصال
# =========================

client = spluspy.Client(SESSION_NAME)
clock_task = None


async def update_profile_name():
    new_name = make_profile_name()

    try:
        await client.update_profile(first_name=new_name)
        logging.info("نام پروفایل به‌روزرسانی شد: %s", new_name)
    except Exception:
        logging.exception("خطا در تغییر نام پروفایل")


async def clock_worker():
    last_minute = None

    while config.get("clock_enabled", False):
        try:
            now = datetime.now(TEHRAN)
            minute = now.strftime("%Y-%m-%d %H:%M")

            if minute != last_minute:
                await update_profile_name()
                last_minute = minute

            now = datetime.now(TEHRAN)
            wait_time = 60 - now.second - now.microsecond / 1_000_000

            await asyncio.sleep(max(0.05, wait_time))

        except asyncio.CancelledError:
            raise

        except Exception:
            logging.exception("خطا در ساعت")
            await asyncio.sleep(2)


async def start_clock():
    global clock_task

    config["clock_enabled"] = True
    save()

    if clock_task is None or clock_task.done():
        clock_task = asyncio.create_task(clock_worker())

    await update_profile_name()


async def stop_clock():
    global clock_task

    config["clock_enabled"] = False
    save()

    if clock_task and not clock_task.done():
        clock_task.cancel()

        try:
            await clock_task
        except asyncio.CancelledError:
            pass

    clock_task = None

    try:
        await client.update_profile(
            first_name=config.get("base_name", "Mohsen")
        )
    except Exception:
        logging.exception("خطا در بازگرداندن نام پروفایل")


# =========================
# دستورات
# =========================

HELP_TEXT = """
╔════════════════════════════╗
       ✦ MOHSEN SELF BOT ✦
╚════════════════════════════╝

⌚ مدیریت ساعت
!clock on
!clock off
!clock status

👤 نام پروفایل
!clock name Mohsen

🔢 فونت ساعت
!clock font normal
!clock font bold
!clock font double
!clock font random

🔠 فونت نام
!clock namefont normal
!clock namefont bold
!clock namefont italic
!clock namefont random

💬 قالب پیام
!msgfont on
!msgfont off
!msgfont bold
!msgfont italic
!msgfont underline
!msgfont strike

🤖 پاسخ خودکار
!reply on
!reply off
!reply text متن پاسخ

🔍 پیش‌نمایش
!preview

📌 راهنما
!help
"""


async def handle_command(text):
    parts = text.strip().split()
    if not parts:
        return None

    command = parts[0].lower()

    if command in ("!help", "!start"):
        return HELP_TEXT

    if command == "!clock":
        if len(parts) < 2:
            return "دستور نامعتبر است. از !help استفاده کن."

        action = parts[1].lower()

        if action == "on":
            await start_clock()
            return "ساعت پروفایل فعال شد."

        if action == "off":
            await stop_clock()
            return "ساعت پروفایل غیرفعال شد."

        if action == "status":
            return (
                "وضعیت ساعت: "
                + ("فعال" if config["clock_enabled"] else "غیرفعال")
                + "\nنام: " + config["base_name"]
                + "\nفونت ساعت: " + config["clock_font"]
                + "\nفونت نام: " + config["name_font"]
            )

        if action == "name":
            new_name = text.partition(" ")[2].partition(" ")[2].strip()

            if not new_name:
                return "نام جدید را وارد کن."

            config["base_name"] = new_name
            save()

            if config["clock_enabled"]:
                await update_profile_name()
            else:
                await client.update_profile(first_name=new_name)

            return "نام پروفایل تغییر کرد."

        if action == "font":
            if len(parts) < 3:
                return "نام فونت را مشخص کن."

            font = parts[2].lower()

            if font == "random":
                config["random_clock"] = True
            elif font in CLOCK_FONTS:
                config["random_clock"] = False
                config["clock_font"] = font
            else:
                return "فونت معتبر نیست."

            save()

            if config["clock_enabled"]:
                await update_profile_name()

            return "فونت ساعت تنظیم شد."

        if action == "namefont":
            if len(parts) < 3:
                return "نام فونت را مشخص کن."

            font = parts[2].lower()

            if font == "random":
                config["random_name"] = True
            elif font in NAME_FONTS:
                config["random_name"] = False
                config["name_font"] = font
            else:
                return "فونت معتبر نیست."

            save()

            if config["clock_enabled"]:
                await update_profile_name()

            return "فونت نام تنظیم شد."

    if command == "!preview":
        return "پیش‌نمایش نام پروفایل:\n" + make_profile_name()

    if command == "!msgfont":
        if len(parts) < 2:
            return "استفاده: !msgfont on/off/bold/italic/underline/strike"

        value = parts[1].lower()

        if value == "on":
            config["message_font_enabled"] = True
            save()
            return "قالب‌بندی پیام‌ها فعال شد."

        if value == "off":
            config["message_font_enabled"] = False
            save()
            return "قالب‌بندی پیام‌ها غیرفعال شد."

        if value in ("bold", "italic", "underline", "strike"):
            config["message_font"] = value
            config["message_font_enabled"] = True
            save()
            return "قالب پیام روی " + value + " تنظیم شد."

        return "قالب معتبر نیست."

    if command == "!reply":
        if len(parts) < 2:
            return "استفاده: !reply on/off/text"

        action = parts[1].lower()

        if action == "on":
            config["auto_reply"] = True
            save()
            return "پاسخ خودکار فعال شد."

        if action == "off":
            config["auto_reply"] = False
            save()
            return "پاسخ خودکار غیرفعال شد."

        if action == "text":
            new_text = text.partition(" ")[2].partition(" ")[2].strip()

            if not new_text:
                return "متن پاسخ را وارد کن."

            config["reply_text"] = new_text
            save()
            return "متن پاسخ خودکار ذخیره شد."

    return "دستور شناخته نشد. برای راهنما !help را بفرست."


# =========================
# مدیریت پیام‌ها
# =========================

processed_messages = set()


@client.on_message()
async def message_handler(client, event):
    message = getattr(event, "message", None)

    if message is None:
        return

    message_text = (
        getattr(message, "raw_text", None)
        or getattr(message, "message", None)
        or getattr(message, "text", None)
        or ""
    )

    if not message_text:
        return

    is_outgoing = getattr(message, "out", False)

    if is_outgoing:
        if message_text.strip().startswith("!"):
            try:
                response = await handle_command(message_text)

                if response:
                    await event.reply(response)

            except Exception:
                logging.exception("خطا در اجرای دستور")
                await event.reply("در اجرای دستور خطایی رخ داد.")

            return

        if config.get("message_font_enabled", False):
            message_id = getattr(message, "id", None)

            if message_id in processed_messages:
                return

            if message_id is not None:
                processed_messages.add(message_id)

            try:
                style = config.get("message_font", "bold")
                formatted = format_html_message(message_text, style)

                # قالب‌بندی واقعی HTML؛ پشتیبانی این گزینه
                # به نسخه نصب‌شده SplusPy وابسته است.
                await message.edit(
                    text=formatted,
                    parse_mode="html"
                )

            except Exception:
                logging.exception(
                    "ویرایش قالب‌بندی پیام ناموفق بود. "
                    "ممکن است نسخه SplusPy از parse_mode در edit پشتیبانی نکند."
                )

        return

    if config.get("auto_reply", False):
        try:
            await event.reply(config.get("reply_text", "سلام"))
        except Exception:
            logging.exception("خطا در ارسال پاسخ خودکار")


# =========================
# اجرای برنامه
# =========================

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        client.start()

        if config.get("clock_enabled", False):
            loop.create_task(clock_worker())

        logging.info("Mohsen Self Bot started.")
        client.run_until_disconnected()

    except KeyboardInterrupt:
        logging.info("برنامه متوقف شد.")

    except Exception:
        logging.exception("خطا در اجرای برنامه")

    finally:
        try:
            client.disconnect()
        except Exception:
            pass

        if not loop.is_closed():
            loop.close()


if __name__ == "__main__":
    main()
