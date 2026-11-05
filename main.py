import json
import urllib.request
from datetime import datetime

API = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=100"

def get_data():
    request = urllib.request.Request(
        API,
        headers={"User-Agent": "WHJ-Bot"}
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())

def analyze():
    candles = get_data()
    prices = [float(c[4]) for c in candles]

    sma20 = sum(prices[-20:]) / 20
    sma50 = sum(prices[-50:]) / 50
    price = prices[-1]

    if price > sma20 > sma50:
        signal = "BUY"
    elif price < sma20 < sma50:
        signal = "SELL"
    else:
        signal = "HOLD"

    return {
        "project": "WHJ Bitcoin Bot",
        "time": datetime.utcnow().isoformat(),
        "BTC_price": price,
        "SMA20": round(sma20, 2),
        "SMA50": round(sma50, 2),
        "signal": signal
    }

if __name__ == "__main__":
    try:
        print(json.dumps(analyze(), indent=4))
    except Exception as error:
        print("WHJ Error:", error)