from datetime import datetime, timezone, timedelta
from dateutil import parser as dateutil_parser
from typing import Optional, Any, Dict

def _try_parse_date(val: Any) -> Optional[datetime]:
    """Coerce val (str/int/float/datetime) to timezone-aware datetime or return None."""
    if val is None:
        return None

    # If already datetime
    if isinstance(val, datetime):
        dt = val
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # If numeric unix timestamp (s or ms)
    if isinstance(val, (int, float)):
        try:
            if val > 1e12:  # milliseconds
                return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
            elif val > 1e9:  # seconds
                return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            pass

    # If it's a numeric string, try converting to int
    if isinstance(val, str) and val.isdigit():
        try:
            n = int(val)
            return _try_parse_date(n)
        except Exception:
            pass

    # If string date, try dateutil
    if isinstance(val, str):
        s = val.strip()
        # normalize trailing Z
        if s.endswith("Z") and not s.endswith("+00:00"):
            s = s.replace("Z", "+00:00")
        try:
            dt = dateutil_parser.isoparse(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            try:
                dt = dateutil_parser.parse(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                return None

    return None


def safe_get_start_date(market: Dict, client=None, allow_activity_fallback: bool = False) -> Optional[datetime]:
    """
    Find a best-effort 'market start' datetime. Prioritises:
    1) accepting_order_timestamp (likely when market opened)
    2) game_start_time (if that is actually a launch indicator in your domain)
    3) common created/published keys
    4) nested fields under meta/attributes/info
    5) optional activity fallback (expensive) if allow_activity_fallback=True
    Returns timezone-aware datetime or None.
    """
    if not isinstance(market, dict):
        return None

    # 1) best guess: accepting_order_timestamp (common in your API)
    if "accepting_order_timestamp" in market:
        dt = _try_parse_date(market.get("accepting_order_timestamp"))
        if dt:
            return dt

    # 2) sometimes game_start_time exists (ISO) — this isn't creation but may be useful
    if "game_start_time" in market:
        dt = _try_parse_date(market.get("game_start_time"))
        if dt:
            return dt

    # 3) other common top-level keys
    candidates = (
        "start_date", "startDate", "created_at", "createdAt", "published_at",
        "publishedAt", "launch_time", "opened_at", "open_date", "publish_date",
        "publishedDate", "creation_time", "created", "timestamp"
    )
    for k in candidates:
        if k in market:
            dt = _try_parse_date(market.get(k))
            if dt:
                return dt

    # 4) nested possible parents
    for parent in ("meta", "attributes", "metadata", "data", "details", "info"):
        nested = market.get(parent)
        if isinstance(nested, dict):
            for k in candidates:
                if k in nested:
                    dt = _try_parse_date(nested.get(k))
                    if dt:
                        return dt

    # 5) optional slow fallback: infer from earliest activity/trade
    if allow_activity_fallback and client is not None:
        try:
            resp = client.get_market_activity(market_id=market.get("id") or market.get("market_id"))
            events = resp.get("data") or resp or []
            min_ts = None
            for ev in events:
                for tk in ("created_at", "createdAt", "timestamp", "time", "ts"):
                    t = ev.get(tk)
                    if not t:
                        continue
                    dt = _try_parse_date(t)
                    if dt and (min_ts is None or dt < min_ts):
                        min_ts = dt
            if min_ts:
                return min_ts
        except Exception:
            pass

    # Not found
    return None


def is_recent_market(market: Dict, days: int, client=None, treat_unknown_as_recent: bool = True) -> bool:
    """Return True if the market started within the last X days."""
    start_dt = safe_get_start_date(market, client=client, allow_activity_fallback=False)
    if not start_dt:
        return bool(treat_unknown_as_recent)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    return start_dt >= (datetime.now(timezone.utc) - timedelta(days=days))


def market_age_days(market: Dict) -> Optional[float]:
    """Return market age in days (float) or None if unknown."""
    sd = safe_get_start_date(market)
    if not sd:
        return None
    now = datetime.now(timezone.utc)
    return (now - sd).total_seconds() / 86400.0


def safe_get_price(outcome: Dict) -> Optional[float]:
    """Try multiple common keys for price, return None if not found or invalid."""
    if not isinstance(outcome, dict):
        return None
    for k in ("price", "lastPrice", "outcome_price", "probability"):
        v = outcome.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return None


def safe_get_outcome_id(outcome: Dict) -> Optional[Any]:
    for k in ("token_id", "id", "outcome_id", "outcomeId"):
        if k in outcome:
            return outcome[k]
    # fallback to name if no id present
    return outcome.get("name") or outcome.get("label")


def safe_get_outcome_name(outcome: Dict) -> str:
    return outcome.get("outcome") or outcome.get("name") or outcome.get("label") or "UNKNOWN"


def safe_get_market_id(market: Dict) -> Optional[Any]:
    for k in ("id", "market_id", "marketId"):
        if k in market:
            return market[k]
    # fallback to question string (not ideal but usable)
    return market.get("question")


def parse_end_date(market: Dict) -> Optional[datetime]:
    # try a few keys / formats, return datetime or None
    for k in ("end_date_iso", "endDate", "end_date", "end"):
        s = market.get(k)
        if not s:
            continue
        # normalize Z to +00:00
        try:
            s2 = s.replace("Z", "+00:00") if isinstance(s, str) else s
            return datetime.fromisoformat(s2)
        except Exception:
            continue
    return None


def safe_get_volume(market: Dict) -> float:
    # try some common volume keys
    for k in ("volume", "24h_volume", "volume_24h", "total_volume"):
        v = market.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return 0.0