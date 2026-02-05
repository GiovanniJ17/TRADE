"""
Currency conversion USD <-> EUR for display (trading in Italy / Trade Republic)

Enhanced per Code Review Issue #7:
- Dynamic exchange rate fetching from free API
- 24-hour caching to database
- Fallback to config/default if API fails
"""
from typing import Optional, Tuple
from datetime import datetime, timedelta
import requests
from loguru import logger

# Module-level cache (in-memory, supplementing DB cache)
_rate_cache = {
    'rate': None,
    'timestamp': None
}

# Cache duration
CACHE_HOURS = 24


def _fetch_exchange_rate_from_api() -> Optional[float]:
    """
    Fetch current USD/EUR rate from free exchange rate API.
    
    Uses exchangerate-api.com (free tier: 1500 requests/month).
    Returns None if API call fails.
    """
    try:
        # Free API - no key required
        response = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            rate = data.get('rates', {}).get('EUR')
            if rate:
                logger.debug(f"Fetched exchange rate from API: USD/EUR = {rate}")
                return float(rate)
    except requests.RequestException as e:
        logger.debug(f"Exchange rate API request failed: {e}")
    except (KeyError, ValueError, TypeError) as e:
        logger.debug(f"Exchange rate API response parsing failed: {e}")
    
    return None


def _get_cached_rate(user_db) -> Optional[dict]:
    """Get cached rate from database if not expired."""
    if not user_db:
        return None
    
    try:
        rate_str = user_db.get_setting("cached_exchange_rate")
        timestamp_str = user_db.get_setting("cached_exchange_rate_timestamp")
        
        if rate_str and timestamp_str:
            rate = float(rate_str)
            timestamp = datetime.fromisoformat(timestamp_str)
            age_hours = (datetime.now() - timestamp).total_seconds() / 3600
            
            if age_hours < CACHE_HOURS:
                return {
                    'rate': rate,
                    'timestamp': timestamp,
                    'age_hours': age_hours
                }
    except (TypeError, ValueError) as e:
        logger.debug(f"Could not read cached exchange rate: {e}")
    
    return None


def _cache_rate(user_db, rate: float):
    """Cache rate to database."""
    if not user_db:
        return
    
    try:
        user_db.set_setting("cached_exchange_rate", str(rate))
        user_db.set_setting("cached_exchange_rate_timestamp", datetime.now().isoformat())
        logger.debug(f"Cached exchange rate to DB: {rate}")
    except Exception as e:
        logger.debug(f"Could not cache exchange rate: {e}")


def get_exchange_rate(user_db=None, config=None, force_refresh: bool = False) -> float:
    """
    Get USD->EUR exchange rate with automatic fetching and caching.
    
    Priority:
    1. User-set rate in database (manual override)
    2. Fresh API rate (if cache expired or force_refresh)
    3. Cached rate from database (within 24 hours)
    4. In-memory cache (within session)
    5. Config default
    6. Hardcoded fallback (0.92)
    
    Args:
        user_db: UserDatabase instance for caching
        config: Config object for default rate
        force_refresh: If True, fetch fresh rate from API
        
    Returns:
        USD to EUR exchange rate
    """
    global _rate_cache
    
    # 1. Check for user-set manual override
    if user_db:
        try:
            manual_rate = user_db.get_setting("exchange_rate")
            if manual_rate:
                return float(manual_rate)
        except (TypeError, ValueError):
            pass
    
    # 2. Check if we need to refresh (cache expired or forced)
    need_refresh = force_refresh
    
    # Check in-memory cache first
    if not need_refresh and _rate_cache['rate'] and _rate_cache['timestamp']:
        age_hours = (datetime.now() - _rate_cache['timestamp']).total_seconds() / 3600
        if age_hours < CACHE_HOURS:
            return _rate_cache['rate']
        need_refresh = True
    
    # Check DB cache
    if not need_refresh:
        cached = _get_cached_rate(user_db)
        if cached and cached['age_hours'] < CACHE_HOURS:
            # Update in-memory cache
            _rate_cache['rate'] = cached['rate']
            _rate_cache['timestamp'] = cached['timestamp']
            return cached['rate']
        need_refresh = True
    
    # 3. Fetch fresh rate from API
    if need_refresh:
        fresh_rate = _fetch_exchange_rate_from_api()
        if fresh_rate:
            # Update both caches
            _rate_cache['rate'] = fresh_rate
            _rate_cache['timestamp'] = datetime.now()
            _cache_rate(user_db, fresh_rate)
            return fresh_rate
    
    # 4. Fallback to any cached rate (even if slightly old)
    if _rate_cache['rate']:
        logger.warning(f"Using stale in-memory rate: {_rate_cache['rate']}")
        return _rate_cache['rate']
    
    cached = _get_cached_rate(user_db)
    if cached:
        logger.warning(f"Using stale DB cached rate: {cached['rate']}")
        return cached['rate']
    
    # 5. Fallback to config
    if config:
        try:
            r = config.get("risk.exchange_rate")
            if r is not None:
                logger.warning(f"Using config rate: {r}")
                return float(r)
        except (TypeError, ValueError):
            pass
    
    # 6. Final hardcoded fallback
    logger.warning("Using hardcoded fallback rate: 0.92")
    return 0.92


def use_eur_for_display(user_db=None) -> bool:
    """Whether to show prices in EUR (True) or USD (False)."""
    if not user_db:
        return False
    s = user_db.get_setting("display_currency_eur")
    return s and s.lower() == "true"


def usd_to_eur(amount_usd: float, rate: float) -> float:
    """Convert USD amount to EUR using given rate (1 USD = rate EUR)."""
    if amount_usd is None:
        return None
    return amount_usd * rate


def format_price(
    amount_usd: Optional[float],
    use_eur: bool = False,
    rate: Optional[float] = None,
) -> str:
    """Format price for display: either USD or EUR.
    
    If rate is not provided, fetches current rate dynamically.
    """
    if amount_usd is None:
        return "N/A"
    try:
        val = float(amount_usd)
    except (TypeError, ValueError):
        return "N/A"
    if use_eur:
        if rate is None:
            rate = get_exchange_rate()  # Get dynamic rate
        return f"€{(val * rate):.2f}"
    return f"${val:.2f}"
