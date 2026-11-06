import json
import urllib.request
from datetime import datetime, timezone

API = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60"


def get_data():
    request = urllib.request.Request(
        API,
        headers={"User-Agent": "WHJ-Bitcoin-Bot/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("error"):
        raise RuntimeError(str(data["error"]))

    result = data["result"]
    pair_key = next(k for k in result if k != "last")

    return [float(candle[4]) for candle in result[pair_key]]


def analyze():
    prices = get_data()

    if len(prices) < 50:
        raise ValueError("Not enough market data")

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
        "time": datetime.now(timezone.utc).isoformat(),
        "BTC_price": price,
        "SMA20": round(sma20, 2),
        "SMA50": round(sma50, 2),
        "signal": signal
    }


if __name__ == "__main__":
    try:
        print(json.dumps(analyze(), indent=4))
    except Exception as error:
        print("WHJ Error:", str(error))