from fastapi import APIRouter, HTTPException, Query, Request

from app.market_data.aggregator import GRANULARITY_SECONDS

router = APIRouter()


@router.get("/api/candles")
async def get_candles(
    request: Request,
    granularity: str = Query("M1"),
    count: int = Query(300, ge=1, le=5000),
):
    if granularity not in GRANULARITY_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported granularity {granularity!r}; expected one of {list(GRANULARITY_SECONDS)}",
        )

    broker = request.app.state.broker
    instrument = request.app.state.instrument
    candles = await broker.get_candles(instrument, granularity, count)

    return {
        "instrument": instrument,
        "granularity": granularity,
        "candles": [
            {
                "time": int(c.time.timestamp()),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
            }
            for c in candles
        ],
    }
