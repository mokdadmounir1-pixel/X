"""Open-source projects worth wiring into the lab. `pip` entries are installed and
smoke-tested for real by `python -m quantlab install`; `git` entries are shallow-cloned
into vendor/ for reading/forking (strategy ideas, execution engines)."""

# id, kind, target, import name, category, why it matters for scalping research
TOOLS = [
    ("ccxt", "pip", "ccxt", "ccxt", "data/exec", "Unified API for 100+ exchanges: OHLCV, order books, orders"),
    ("websockets", "pip", "websockets", "websockets", "data/exec", "Low-latency streaming feeds"),
    ("aiohttp", "pip", "aiohttp", "aiohttp", "data/exec", "Async REST for parallel multi-pair fetching"),
    ("yfinance", "pip", "yfinance", "yfinance", "data", "Free FX/equity/crypto history for out-of-sample checks"),
    ("py-clob-client", "pip", "py-clob-client", "py_clob_client", "data/exec", "Official Polymarket CLOB client (5-min BTC binary markets)"),
    ("pandas-ta-classic", "pip", "pandas-ta-classic", "pandas_ta_classic", "indicators", "130+ indicators (maintained fork of pandas-ta)"),
    ("backtesting.py", "pip", "backtesting jinja2", "backtesting", "backtest", "Fast second-opinion backtester + optimiser heatmaps"),
    ("vectorbt", "pip", "vectorbt", "vectorbt", "backtest", "Vectorised backtests over thousands of parameter combos"),
    ("hftbacktest", "pip", "hftbacktest", "hftbacktest", "backtest", "Tick/L2 order-book backtester with queue-position model"),
    ("quantstats", "pip", "quantstats", "quantstats", "analytics", "Tear sheets: Sharpe, Sortino, drawdowns, monthly returns"),
    ("scipy", "pip", "scipy", "scipy", "analytics", "Statistics / optimisation"),
    ("statsmodels", "pip", "statsmodels", "statsmodels", "analytics", "Cointegration, ADF, regressions (stat-arb / pairs)"),
    ("arch", "pip", "arch", "arch", "analytics", "GARCH volatility forecasts for ATR/stop sizing"),
    ("numba", "pip", "numba", "numba", "perf", "JIT for tight backtest loops"),
    ("scikit-learn", "pip", "scikit-learn", "sklearn", "ml", "Baseline ML models, calibration, CV"),
    ("lightgbm", "pip", "lightgbm", "lightgbm", "ml", "Gradient boosting for direction/probability models"),
    ("xgboost", "pip", "xgboost", "xgboost", "ml", "Gradient boosting alternative"),
    ("hmmlearn", "pip", "hmmlearn", "hmmlearn", "ml", "Hidden-Markov regime detection (trend / range / chaos)"),
    ("river", "pip", "river", "river", "ml", "Online learning that adapts bar by bar"),
    ("optuna", "pip", "optuna", "optuna", "optim", "Bayesian hyper-parameter search"),
    ("skfolio", "pip", "skfolio", "skfolio", "portfolio", "Portfolio allocation across strategies"),
    ("riskfolio-lib", "pip", "riskfolio-lib", "riskfolio", "portfolio", "Risk-parity / CVaR allocation"),
    ("freqtrade", "pip", "freqtrade", "freqtrade", "framework", "Full crypto bot framework (pip build of sdnotify fails on some systems; freqtrade-src is cloned as fallback)"),
    ("nautilus_trader", "pip", "nautilus_trader", "nautilus_trader", "framework", "Production event-driven engine (Rust core)"),
    ("pytest", "pip", "pytest", "pytest", "quality", "Test-suite runner"),
    ("freqtrade-src", "git", "https://github.com/freqtrade/freqtrade", None, "framework", "Strategy examples + hyperopt loss functions"),
    ("hummingbot-src", "git", "https://github.com/hummingbot/hummingbot", None, "framework", "Market-making / arbitrage strategy sources"),
    ("jesse-src", "git", "https://github.com/jesse-ai/jesse", None, "framework", "Clean strategy API + indicators"),
    ("backtrader-src", "git", "https://github.com/mementum/backtrader", None, "backtest", "Classic event-driven engine, many community strategies"),
    ("qlib-src", "git", "https://github.com/microsoft/qlib", None, "ml", "Quant ML research platform (alpha factors)"),
    ("FinRL-src", "git", "https://github.com/AI4Finance-Foundation/FinRL", None, "ml", "Reinforcement-learning trading environments"),
    ("py-clob-client-src", "git", "https://github.com/Polymarket/py-clob-client", None, "data/exec", "Reference for Polymarket order flow"),
]
