import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

# 🔐 ENV VARIABLES (set in Railway)
API_KEY = os.getenv("OANDA_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# OANDA endpoint (demo)
OANDA_URL = "https://api-fxpractice.oanda.com/v3/instruments/XAU_USD/candles"

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

# CRT only needs the last two *completed* candles; latest may still be incomplete.
CANDLE_COUNT = 4

# Poll shortly after each UTC hour — OANDA H1/H4 align to UTC; no new fully closed bar between hours.
# Slightly late so `complete` is usually true (increase if alerts lag or are missed).
POLL_SECONDS_PAST_HOUR = 30
MIN_SLEEP_SEC = 5.0

# store last processed candle times per timeframe (to avoid duplicate alerts)
last_candle_time_by_tf = {
    "H1": None,
    "H4": None,
}


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


# 📊 Fetch candles (OANDA allows one granularity per request; reuse session + parallelize H1/H4.)
def get_candles(session, granularity):
    params = {
        "granularity": granularity,
        "count": CANDLE_COUNT,
        "price": "M",
    }

    r = session.get(OANDA_URL, params=params, timeout=20)
    data = r.json()

    if "candles" not in data:
        print("❌ API Error:", data)
        return []

    return data["candles"]


def fetch_candles_for_timeframes(session, executor, timeframes):
    """Both granularities in parallel; executor is reused across loop iterations."""
    future_to_tf = {
        executor.submit(get_candles, session, tf): tf for tf in timeframes
    }
    out = {}
    for fut in as_completed(future_to_tf):
        tf = future_to_tf[fut]
        out[tf] = fut.result()
    return out


def seconds_until_next_poll_utc(now=None, past_second=POLL_SECONDS_PAST_HOUR):
    """Sleep until the next fixed UTC slot …:00:30 (if past_second=30).

    Uses the *wall clock* each time (datetime.now(UTC)), not (last_sleep + 1h).
    The +past_second offset does **not** accumulate — every poll targets the same
    pattern: 12:00:30, 13:00:30, 14:00:30 UTC, etc.
    """
    now = now or datetime.now(timezone.utc)
    anchor = now.replace(minute=0, second=0, microsecond=0) + timedelta(
        seconds=past_second
    )
    if now <= anchor:
        return max((anchor - now).total_seconds(), MIN_SLEEP_SEC)
    next_anchor = anchor + timedelta(hours=1)
    return max((next_anchor - now).total_seconds(), MIN_SLEEP_SEC)


# 🧠 CRT logic (2-candle sweep/reclaim model using ONLY closed candles)
def detect_crt(candles):
    completed = [c for c in candles if c["complete"]]

    if len(completed) < 2:
        return None, None

    c1 = completed[-2]
    c2 = completed[-1]

    h1 = float(c1["mid"]["h"])
    l1 = float(c1["mid"]["l"])
    h2 = float(c2["mid"]["h"])
    l2 = float(c2["mid"]["l"])
    close2 = float(c2["mid"]["c"])

    candle_time = c2["time"]

    print(
        f"Checking CRT -> c1:{c1['time']} c2:{c2['time']} "
        f"| c1(H:{h1},L:{l1}) c2(H:{h2},L:{l2},C:{close2})"
    )

    # 🟢 Bullish CRT:
    # c2 sweeps below c1 low and closes back above c1 low,
    # while c1 high remains above c2 high.
    if l2 < l1 and close2 > l1 and h1 > h2:
        return "🟢 Bullish CRT", candle_time

    # 🔴 Bearish CRT:
    # c2 sweeps above c1 high and closes back below c1 high,
    # while c1 low remains below c2 low.
    if h2 > h1 and close2 < h1 and l1 < l2:
        return "🔴 Bearish CRT", candle_time

    return None, candle_time


# 📤 Send Telegram alert
def send_telegram(session, message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:
        session.post(url, json=payload, timeout=20)
    except Exception as e:
        print("Telegram Error:", e)


def main():
    validate_env()
    print(
        "Bot started. Polling OANDA shortly after each UTC hour "
        f"(+{POLL_SECONDS_PAST_HOUR}s); H1/H4 fetched in parallel."
    )

    timeframes = ("H1", "H4")

    with requests.Session() as oanda, requests.Session() as telegram:
        oanda.headers.update(headers)

        with ThreadPoolExecutor(max_workers=len(timeframes)) as executor:
            # 🔁 MAIN LOOP
            while True:
                try:
                    candles_by_tf = fetch_candles_for_timeframes(
                        oanda, executor, timeframes
                    )

                    for timeframe in timeframes:
                        candles = candles_by_tf.get(timeframe, [])

                        if candles:
                            signal, candle_time = detect_crt(candles)

                            # send alert only once per candle per timeframe
                            if signal and candle_time != last_candle_time_by_tf[timeframe]:
                                message = f"GOLD/{timeframe} {signal}"
                                print("🚀 Sending:", message)

                                send_telegram(telegram, message)

                                last_candle_time_by_tf[timeframe] = candle_time

                    time.sleep(seconds_until_next_poll_utc())

                except Exception as e:
                    print("Error:", e)
                    time.sleep(MIN_SLEEP_SEC)


if __name__ == "__main__":
    main()
