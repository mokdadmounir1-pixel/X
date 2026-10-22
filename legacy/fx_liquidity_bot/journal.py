import pandas as pd


def build_journal(scanner) -> pd.DataFrame:
    """Consolidated log of every signal stage for every pair -- including
    rejections -- so it's always clear why the bot did or didn't enter."""
    rows = []
    for engine in scanner.engines.values():
        rows.extend(engine.journal)
    rows.extend(scanner.journal)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
