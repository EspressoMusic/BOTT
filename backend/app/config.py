from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_source: str = "oanda"  # "oanda" | "yahoo" | "twelvedata" | "mt5"

    oanda_api_token: str = ""
    oanda_account_id: str = ""
    oanda_environment: str = "practice"  # "practice" | "live"
    instrument: str = "XAU_USD"
    strategy_granularity: str = "M1"
    allow_live_trading: bool = False
    execution_mode: str = "simulated"  # "simulated" (paper, default) | "live" (real orders via data_source's broker)
    cors_origins: list[str] = ["http://localhost:5173"]

    openai_api_key: str = ""  # needed for the "ask the bot" chat feature
    twelvedata_api_key: str = ""  # DATA_SOURCE=twelvedata — near-real-time gold data, no broker account needed

    # DATA_SOURCE=mt5 — attaches to a MetaTrader 5 terminal already running/logged-in on
    # this machine. mt5_login/password/server are only needed if you want the adapter to
    # drive the terminal's login itself instead of using whatever account is already open.
    mt5_symbol: str = "XAUUSD"
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_terminal_path: str = ""

    # Optional trade-opened/closed notifications via a Telegram bot — both empty
    # means the feature is simply off (see app/notify/telegram.py).
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


settings = Settings()
