"""Adaptateur vers les conversions de devise du bot FX existant."""
from fx_liquidity_bot.instruments import PIP_SIZE, pnl_usd  # noqa: F401


def loss_at(pair: str, entry: float, stop: float, direction: str) -> float:
    """Perte USD par unité si le prix atteint `stop` (valeur positive)."""
    return max(0.0, -pnl_usd(pair, entry, stop, direction, 1))
