"""How old is what Home Assistant knows about a device (cloud devices can lag or drop)."""
import datetime as _dt
from typing import Optional

STALE_AFTER_MIN = 15  # older data gets a warning, so Leyla never presents it as current


def age_minutes(st: dict, now: Optional[_dt.datetime] = None) -> Optional[int]:
    """Minutes since Home Assistant last heard from the entity (last_reported, else
    last_updated), or None when the state carries no usable time."""
    stamp = st.get("last_reported") or st.get("last_updated") or st.get("last_changed")
    try:
        then = _dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=_dt.timezone.utc)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return max(0, int((now - then).total_seconds() // 60))
