from flask import Flask, request
import rubpy

app = Flask(__name__)

# توکن رباتت
TOKEN = "DFDAJ0KMLKTSXLMCMKKCROMEITZVWFEGOVEJYFZLLGNGARZTIJJGGMMGNVHEKZIM"

# ساخت کلاینت روبیکا
client = rubpy.Client(TOKEN)

@app.route("/", methods=["GET"])
def home():
    return "Robot is running ✅"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data:
        return "No data", 400

    # تست پیام
    if "message" in data:
        chat_id = data["message"]["chat_id"]
        text = data["message"]["text"]

        # اگر کسی نوشت "سلام" → جواب بده
        if text == "سلام":
            client.send_message(chat_id, "سلام دوست عزیز 🌹")

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
