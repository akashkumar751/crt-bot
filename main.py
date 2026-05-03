import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

# 🔐 ENV VARIABLES (set in Railway)
API_KEY = os.getenv("OANDA_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# OANDA REST base (demo); instrument is appended per request.
OANDA_INSTRUMENTS_BASE = "https://api-fxpractice.oanda.com/v3/instruments"

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

# CRT only needs the last two *completed* candles; latest may still be incomplete.
CANDLE_COUNT = 4

# Wake on each UTC minute boundary (:00) after work — matches OANDA candle time (UTC); no long-term drift.

# label = Telegram prefix; instrument = OANDA v3 name (e.g. BTC_USD, XAU_USD)
WATCHLIST = (
    {"label": "GOLD", "instrument": "XAU_USD", "timeframes": ("H1", "H4")},
    {"label": "BTCUSD", "instrument": "BTC_USD", "timeframes": ("H4",)},
)

# last closed candle time per (instrument, timeframe) — avoids duplicate alerts
last_candle_time_by_instrument_tf = {}


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


# 📊 Fetch candles (OANDA allows one granularity per request; parallelize per instrument/tf.)
def get_candles(session, instrument, granularity):
    url = f"{OANDA_INSTRUMENTS_BASE}/{instrument}/candles"
    params = {
        "granularity": granularity,
        "count": CANDLE_COUNT,
        "price": "M",
    }

    r = session.get(url, params=params, timeout=20)
    data = r.json()

    if "candles" not in data:
        print("❌ API Error:", data)
        return []

    return data["candles"]


def fetch_candles_jobs(session, executor, jobs):
    """jobs: tuple of (instrument, granularity); parallel fetch; executor reused each loop."""
    future_to_key = {
        executor.submit(get_candles, session, inst, tf): (inst, tf)
        for inst, tf in jobs
    }
    out = {}
    for fut in as_completed(future_to_key):
        key = future_to_key[fut]
        out[key] = fut.result()
    return out


def sleep_until_next_utc_minute():
    """Sleep until the start of the next calendar UTC minute (e.g. work ends 10:00:45 → wake ~10:01:00)."""
    now = datetime.now(timezone.utc)
    nxt = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    delay = (nxt - now).total_seconds()
    if delay < 0.05:
        nxt += timedelta(minutes=1)
        delay = (nxt - now).total_seconds()
    time.sleep(delay)


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
    jobs = tuple(
        (entry["instrument"], tf)
        for entry in WATCHLIST
        for tf in entry["timeframes"]
    )
    max_workers = max(1, len(jobs))

    print(
        "Bot started. After each cycle, sleeps until the next UTC minute (:00); "
        f"{len(jobs)} candle request(s) in parallel."
    )

    with requests.Session() as oanda, requests.Session() as telegram:
        oanda.headers.update(headers)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 🔁 MAIN LOOP
            while True:
                try:
                    candles_by_inst_tf = fetch_candles_jobs(
                        oanda, executor, jobs
                    )

                    alert_lines = []
                    for entry in WATCHLIST:
                        label = entry["label"]
                        instrument = entry["instrument"]
                        for timeframe in entry["timeframes"]:
                            candles = candles_by_inst_tf.get(
                                (instrument, timeframe), []
                            )

                            if candles:
                                signal, candle_time = detect_crt(candles)

                                key = (instrument, timeframe)
                                prev = last_candle_time_by_instrument_tf.get(key)
                                if signal and candle_time != prev:
                                    alert_lines.append(
                                        (key, candle_time, label, timeframe, signal)
                                    )

                    if alert_lines:
                        for key, candle_time, *_ in alert_lines:
                            last_candle_time_by_instrument_tf[key] = candle_time
                        message = "\n".join(
                            f"{label}/{timeframe}: {signal}"
                            for _, _, label, timeframe, signal in alert_lines
                        )
                        print("🚀 Sending:", message)
                        send_telegram(telegram, message)

                    sleep_until_next_utc_minute()

                except Exception as e:
                    print("Error:", e)
                    sleep_until_next_utc_minute()


if __name__ == "__main__":
    main()
