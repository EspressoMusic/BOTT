"""Canonical list of instruments the asset picker can switch between.

`id` doubles as the OANDA instrument code. `mt5_symbol` is the matching
MetaTrader 5 Market Watch symbol (no underscore, the typical broker naming —
see MT5Adapter.set_symbol). Yahoo and Twelve Data ignore both and always
serve gold regardless of what's asked, so they never support switching (see
app.state.supports_instrument_switch in main.py).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class InstrumentInfo:
    id: str
    label: str
    mt5_symbol: str


AVAILABLE_INSTRUMENTS: list[InstrumentInfo] = [
    InstrumentInfo(id="XAU_USD", label="זהב", mt5_symbol="XAUUSD"),
    InstrumentInfo(id="EUR_USD", label="יורו/דולר", mt5_symbol="EURUSD"),
    InstrumentInfo(id="BTC_USD", label="ביטקוין", mt5_symbol="BTCUSD"),
]

_LABELS = {i.id: i.label for i in AVAILABLE_INSTRUMENTS}
_BY_ID = {i.id: i for i in AVAILABLE_INSTRUMENTS}


def instrument_label(instrument_id: str) -> str:
    return _LABELS.get(instrument_id, instrument_id)


def find_instrument(instrument_id: str) -> InstrumentInfo | None:
    return _BY_ID.get(instrument_id)
