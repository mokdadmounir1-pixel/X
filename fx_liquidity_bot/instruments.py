PIP_SIZE = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.01,
    "AUDUSD": 0.0001,
    "USDCAD": 0.0001,
    "USDCHF": 0.0001,
    "NZDUSD": 0.0001,
}

BASE_PRICE = {
    "EURUSD": 1.0850,
    "GBPUSD": 1.2650,
    "USDJPY": 149.50,
    "AUDUSD": 0.6550,
    "USDCAD": 1.3650,
    "USDCHF": 0.8800,
    "NZDUSD": 0.6050,
}

PAIRS = list(PIP_SIZE.keys())

LOT_UNITS = 100_000


def pip_value_usd(pair: str, price: float, lot_units: int = LOT_UNITS) -> float:
    """USD value of one pip move for `lot_units` of `pair`, using the current
    price as an approximate quote->USD conversion rate for USD-base pairs."""
    pip = PIP_SIZE[pair]
    quote = pair[3:]
    if quote == "USD":
        return pip * lot_units
    return pip * lot_units / price


def pnl_usd(pair: str, entry: float, exit_price: float, direction: str, units: float) -> float:
    sign = 1 if direction == "long" else -1
    pnl_quote = (exit_price - entry) * sign * units
    quote = pair[3:]
    if quote == "USD":
        return pnl_quote
    return pnl_quote / exit_price
