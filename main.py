import requests
import time
import os
from datetime import datetime

# 🔐 ENV VARIABLES (set in Railway)
API_KEY = os.getenv("OANDA_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# OANDA endpoint (demo)
OANDA_URL = "https://api-fxpractice.oanda.com/v3/instruments/XAU_USD/candles"

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

# store last processed candle time (to avoid duplicate alerts)
last_candle_time = None


# Validate required configuration before starting loop
def validate_env():
    required_vars = {
        "OANDA_API_KEY": API_KEY,
        "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
        "TELEGRAM_CHAT_ID": CHAT_ID,
    }
    missing = [name for name, value in required_vars.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


# 📊 Fetch candles
def get_candles():
    params = {
        "granularity": "H1",
        "count": 5,
        "price": "M"
    }

    r = requests.get(OANDA_URL, headers=headers, params=params, timeout=20)
    data = r.json()

    if "candles" not in data:
        print("❌ API Error:", data)
        return []

    return data["candles"]


# 🧠 CRT logic (2-candle model using ONLY closed candles)
def detect_crt(candles):
    completed = [c for c in candles if c["complete"]]

    if len(completed) < 2:
        return None, None

    c1 = completed[-2]
    c2 = completed[-1]

    prev_high = float(c1["mid"]["h"])
    prev_low = float(c1["mid"]["l"])
    last_close = float(c2["mid"]["c"])

    candle_time = c2["time"]

    print(f"Checking CRT → {c1['time']} vs {c2['time']}")

    # 🟢 Bullish
    if last_close > prev_high:
        return "🟢 Bullish CRT", candle_time

    # 🔴 Bearish
    if last_close < prev_low:
        return "🔴 Bearish CRT", candle_time

    return None, candle_time


# 📤 Send Telegram alert
def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print("Telegram Error:", e)


def main():
    global last_candle_time
    validate_env()
    print("Bot started. Waiting for closed H1 candles...")

    # 🔁 MAIN LOOP
    while True:
        try:
            candles = get_candles()

            if candles:
                signal, candle_time = detect_crt(candles)

                # send alert only once per candle
                if signal and candle_time != last_candle_time:
                    time_now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

                    message = f"GOLD/H1 {signal}\nTime: {time_now} UTC"
                    print("🚀 Sending:", message)

                    send_telegram(message)

                    last_candle_time = candle_time

            time.sleep(60)  # check every 1 min

        except Exception as e:
            print("Error:", e)
            time.sleep(60)


if __name__ == "__main__":
    main()
