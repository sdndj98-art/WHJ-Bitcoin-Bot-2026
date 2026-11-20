"""Broker-aware WHJ market universe: FX, precious metals, commodities and crypto.

This catalog does not assume every broker offers every symbol. MT5 symbols often
use suffixes (e.g. EURUSD.a / XAUUSDm), so callers should pass the broker's
actual symbol names and validate them with symbol_info/quotes before analysis.
No order execution is implemented here.
"""
from __future__ import annotations

import re
from collections import defaultdict

# Broad ISO 4217 currency-code coverage, including less-liquid currencies.
# The connected broker remains the source of truth for actual offered pairs.
FX_CURRENCIES = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB
BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY CNH COP COU CRC
CUC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD
GNF GTQ GYD HKD HNL HRK HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS
KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT
MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK
PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD
SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI
UYU UZS VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XDR XOF XPD XPF XPT
XSU XTS XUA XXX YER ZAR ZMW ZWL
""".split())

# Widely traded majors and crosses; dynamic discovery below adds any broker-listed
# pair whose base and quote are recognized currency codes.
FX_CORE_PAIRS = frozenset("""
EURUSD GBPUSD AUDUSD NZDUSD USDJPY USDCHF USDCAD
EURGBP EURJPY EURCHF EURAUD EURCAD EURNZD EURSEK EURNOK EURDKK EURPLN
GBPJPY GBPCHF GBPAUD GBPCAD GBPNZD GBPSEK GBPNOK
AUDJPY AUDCHF AUDCAD AUDNZD AUDSGD
NZDJPY NZDCHF NZDCAD
CADJPY CADCHF CHFJPY
USDSGD USDHKD USDCNH USDNOK USDSEK USDDKK USDPLN USDHUF USDCZK USDTRY
USDZAR USDMXN USDBRL USDINR USDKRW USDTHB USDIDR USDPHP USDILS USDSAR USDKWD
""".split())

METALS = {
    "XAU": "GOLD",
    "XAG": "SILVER",
    "XPT": "PLATINUM",
    "XPD": "PALLADIUM",
}
METAL_QUOTE_CODES = frozenset("USD EUR GBP AUD CHF JPY".split())

COMMODITY_BASES = {
    "WTI": "CRUDE_OIL_WTI",
    "BRENT": "CRUDE_OIL_BRENT",
    "NG": "NATURAL_GAS",
    "NATGAS": "NATURAL_GAS",
    "COPPER": "COPPER",
}
CRYPTO_BASES = frozenset("""
BTC ETH BNB XRP SOL ADA DOGE DOT LTC BCH LINK AVAX TRX TON XLM
""".split())


def _clean_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        return ""
    return re.sub(r"[^A-Z0-9]", "", symbol.upper().strip())


def classify_symbol(symbol: str) -> str:
    """Return a broad asset class using a broker symbol's leading/trailing codes."""
    s = _clean_symbol(symbol)
    if not s:
        return "UNKNOWN"

    # Broker prefixes/suffixes are tolerated by searching for known instrument codes.
    if any(re.match(rf"^{base}(?:{quote})", s) for base in CRYPTO_BASES for quote in CRYPTO_QUOTES):
        return "CRYPTO"
    if any(s.startswith(code) for code in METALS):
        return "PRECIOUS_METAL"
    if any(s.startswith(base) for base in COMMODITY_BASES):
        return "COMMODITY"

    # Exact 6-character currency pair, or broker suffix after the pair.
    for i in range(0, len(s) - 5):
        pair = s[i:i + 6]
        base, quote = pair[:3], pair[3:]
        if base in FX_CURRENCIES and quote in FX_CURRENCIES:
            return "FOREX"
    return "OTHER"


def discover_market_universe(broker_symbols) -> dict:
    """Classify broker-listed instruments, preserving their exact symbol strings."""
    groups = defaultdict(list)
    for raw in broker_symbols or []:
        name = raw if isinstance(raw, str) else getattr(raw, "name", "")
        if not name:
            continue
        category = classify_symbol(name)
        groups[category].append(name)

    for names in groups.values():
        names.sort(key=str.upper)

    return {
        "source": "broker_symbol_discovery",
        "paper_only": True,
        "live_orders_enabled": False,
        "categories": {
            category: names
            for category, names in sorted(groups.items())
        },
        "coverage": {
            "forex_currency_codes": sorted(FX_CURRENCIES),
            "core_fx_pairs": sorted(FX_CORE_PAIRS),
            "precious_metals": METALS,
            "commodities": COMMODITY_BASES,
            "crypto_bases": sorted(CRYPTO_BASES),
            "note": "Only symbols actually offered by the connected broker can be analyzed. This catalog does not guarantee tradability, liquidity, or data availability.",
        },
    }


def core_market_symbols() -> dict:
    """Return canonical requested symbols; resolve to broker names before use."""
    return {
        "forex": sorted(FX_CORE_PAIRS),
        "metals": ["XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"],
        "commodities": ["WTI", "BRENT", "NATGAS", "COPPER"],
        "crypto": [base + quote for base in sorted(CRYPTO_BASES) for quote in ("USD", "USDT")],
    }
