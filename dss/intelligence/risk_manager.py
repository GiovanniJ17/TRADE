"""
Risk Management Module
Per Trading System Specification v1.0 Section 7

Per-Trade Risk Rules:
- Max Risk Per Trade: 2% of equity
- Max Position Value: 33% of equity
- Max Concurrent Positions: 3-5
- Max Sector Exposure: 40% of equity

Dynamic Stop-Loss:
- ATR-Based: Entry - (ATR × 1.5 for swing, 1.0 for intraday)
- Support-Based: Below nearest support level
- Trailing Stop: After 1× ATR profit, trail at 1.5× ATR

Take-Profit Targets:
- TP1 (Partial): Entry + 1.5× ATR → Sell 50%, move SL to breakeven
- TP2 (Full): Entry + 3× ATR → Close remaining

Drawdown Protection:
- 3 consecutive losses → Reduce to 1% risk
- 5 consecutive losses → Max 1 position
- 6% monthly drawdown → Pause live trading
- 10% monthly drawdown → Stop all trading
"""
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, List
from loguru import logger

from ..utils.config import config
from ..utils.currency import get_exchange_rate


class DrawdownProtection:
    """
    Drawdown protection system per specification.
    Tracks consecutive losses and monthly drawdown to automatically reduce risk.
    """
    
    # Drawdown protection thresholds
    CONSECUTIVE_LOSS_REDUCE_RISK = 3  # Reduce to 1% risk after 3 losses
    CONSECUTIVE_LOSS_MAX_ONE_POSITION = 5  # Max 1 position after 5 losses
    MONTHLY_DRAWDOWN_PAUSE = 6.0  # Pause live trading at 6% monthly drawdown
    MONTHLY_DRAWDOWN_STOP = 10.0  # Stop all trading at 10% monthly drawdown
    
    # Recovery thresholds
    RECOVERY_WINS_FROM_REDUCED_RISK = 2  # 2 wins to recover from 1% risk
    RECOVERY_WINS_FROM_ONE_POSITION = 3  # 3 wins to recover from 1 position max
    
    def __init__(self, user_db=None):
        """
        Initialize with optional user database for persistence.
        
        Args:
            user_db: UserDatabase instance for persistent tracking
        """
        self._user_db = user_db
        
        # In-memory tracking (persisted to DB when available)
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._monthly_start_equity = None
        self._monthly_start_date = None
        self._current_equity = None
        
        # Load from database if available
        if self._user_db:
            self._load_from_db()
    
    def _load_from_db(self):
        """Load protection state from database"""
        try:
            consec_losses = self._user_db.get_setting("drawdown_consecutive_losses")
            if consec_losses:
                self._consecutive_losses = int(consec_losses)
            
            consec_wins = self._user_db.get_setting("drawdown_consecutive_wins")
            if consec_wins:
                self._consecutive_wins = int(consec_wins)
            
            monthly_equity = self._user_db.get_setting("drawdown_monthly_start_equity")
            if monthly_equity:
                self._monthly_start_equity = float(monthly_equity)
            
            monthly_date = self._user_db.get_setting("drawdown_monthly_start_date")
            if monthly_date:
                self._monthly_start_date = datetime.fromisoformat(monthly_date)
            
            current_eq = self._user_db.get_setting("drawdown_current_equity")
            if current_eq:
                self._current_equity = float(current_eq)
        except Exception as e:
            logger.warning(f"Could not load drawdown protection state: {e}")
    
    def _save_to_db(self):
        """Save protection state to database"""
        if not self._user_db:
            return
        
        try:
            self._user_db.set_setting("drawdown_consecutive_losses", str(self._consecutive_losses))
            self._user_db.set_setting("drawdown_consecutive_wins", str(self._consecutive_wins))
            
            if self._monthly_start_equity:
                self._user_db.set_setting("drawdown_monthly_start_equity", str(self._monthly_start_equity))
            if self._monthly_start_date:
                self._user_db.set_setting("drawdown_monthly_start_date", self._monthly_start_date.isoformat())
            if self._current_equity:
                self._user_db.set_setting("drawdown_current_equity", str(self._current_equity))
        except Exception as e:
            logger.warning(f"Could not save drawdown protection state: {e}")
    
    def record_trade_result(self, is_winner: bool, pnl: float = 0):
        """
        Record a trade result to update protection state.
        
        Args:
            is_winner: True if trade was profitable
            pnl: Profit/loss amount
        """
        if is_winner:
            self._consecutive_wins += 1
            self._consecutive_losses = 0
            logger.info(f"Win recorded. Consecutive wins: {self._consecutive_wins}")
        else:
            self._consecutive_losses += 1
            self._consecutive_wins = 0
            logger.info(f"Loss recorded. Consecutive losses: {self._consecutive_losses}")
        
        # Update equity if tracking
        if self._current_equity is not None:
            self._current_equity += pnl
        
        self._save_to_db()
    
    def start_month(self, current_equity: float):
        """
        Start tracking a new month.
        
        Args:
            current_equity: Current account equity
        """
        self._monthly_start_equity = current_equity
        self._monthly_start_date = datetime.now().replace(day=1)
        self._current_equity = current_equity
        self._save_to_db()
        logger.info(f"New month started. Tracking from equity: €{current_equity:,.2f}")
    
    def update_equity(self, current_equity: float):
        """Update current equity for drawdown tracking"""
        self._current_equity = current_equity
        
        # Auto-start month if not tracking
        if self._monthly_start_equity is None:
            self.start_month(current_equity)
        
        # Check if new month
        now = datetime.now()
        if self._monthly_start_date and now.month != self._monthly_start_date.month:
            self.start_month(current_equity)
        
        self._save_to_db()
    
    def get_monthly_drawdown_percent(self) -> float:
        """Calculate current monthly drawdown percentage"""
        if self._monthly_start_equity is None or self._current_equity is None:
            return 0.0
        
        if self._monthly_start_equity <= 0:
            return 0.0
        
        drawdown = (self._monthly_start_equity - self._current_equity) / self._monthly_start_equity * 100
        return max(0.0, drawdown)  # Only count drawdown, not gains
    
    def get_protection_status(self) -> Dict:
        """
        Get current protection status and recommended actions.
        
        Returns:
            Dict with:
            - 'is_trading_allowed': bool
            - 'is_paused': bool (paper trading only)
            - 'is_stopped': bool (no trading)
            - 'risk_multiplier': float (1.0 = normal, 0.5 = reduced)
            - 'max_positions': int
            - 'reasons': list of active restrictions
            - 'recovery_status': dict with recovery progress
        """
        reasons = []
        risk_multiplier = 1.0
        max_positions = config.get("risk.max_positions", 5)
        is_paused = False
        is_stopped = False
        
        # Check consecutive losses
        if self._consecutive_losses >= self.CONSECUTIVE_LOSS_MAX_ONE_POSITION:
            max_positions = 1
            risk_multiplier = 0.5  # Also reduce risk
            reasons.append(f"5+ consecutive losses: Max 1 position, 50% risk")
        elif self._consecutive_losses >= self.CONSECUTIVE_LOSS_REDUCE_RISK:
            risk_multiplier = 0.5  # 1% instead of 2% risk
            reasons.append(f"3+ consecutive losses: Risk reduced to 1%")
        
        # Check monthly drawdown
        monthly_dd = self.get_monthly_drawdown_percent()
        if monthly_dd >= self.MONTHLY_DRAWDOWN_STOP:
            is_stopped = True
            reasons.append(f"10%+ monthly drawdown: ALL TRADING STOPPED")
        elif monthly_dd >= self.MONTHLY_DRAWDOWN_PAUSE:
            is_paused = True
            reasons.append(f"6%+ monthly drawdown: Live trading paused (paper only)")
        
        # Recovery status
        recovery_status = {
            'consecutive_wins': self._consecutive_wins,
            'needs_wins_for_normal_risk': max(0, self.RECOVERY_WINS_FROM_REDUCED_RISK - self._consecutive_wins) if risk_multiplier < 1.0 else 0,
            'needs_wins_for_normal_positions': max(0, self.RECOVERY_WINS_FROM_ONE_POSITION - self._consecutive_wins) if max_positions == 1 else 0
        }
        
        return {
            'is_trading_allowed': not is_stopped,
            'is_paused': is_paused,
            'is_stopped': is_stopped,
            'risk_multiplier': risk_multiplier,
            'max_positions': max_positions,
            'consecutive_losses': self._consecutive_losses,
            'consecutive_wins': self._consecutive_wins,
            'monthly_drawdown_percent': monthly_dd,
            'monthly_start_equity': self._monthly_start_equity,
            'current_equity': self._current_equity,
            'reasons': reasons,
            'recovery_status': recovery_status
        }
    
    def reset(self):
        """Reset all protection tracking (use after full system review)"""
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._save_to_db()
        logger.info("Drawdown protection state reset")


class RiskManager:
    """
    Calculate stop loss, position sizing, and take-profit targets.
    Integrates with DrawdownProtection for automatic risk reduction.
    """
    
    # Class-level cache for user_db and drawdown protection
    _user_db = None
    _drawdown_protection = None
    
    @classmethod
    def get_drawdown_protection(cls) -> DrawdownProtection:
        """Get or create DrawdownProtection instance"""
        if cls._drawdown_protection is None:
            if cls._user_db is None:
                from ..database.user_db import UserDatabase
                cls._user_db = UserDatabase()
            cls._drawdown_protection = DrawdownProtection(cls._user_db)
        return cls._drawdown_protection
    
    @staticmethod
    def calculate_stop_loss(entry_price: float, atr: float, 
                           multiplier: Optional[float] = None,
                           trade_type: str = "swing") -> float:
        """
        Calculate stop loss using ATR-based method.
        
        Per spec:
        - Swing trades: ATR × 1.5
        - Intraday: ATR × 1.0
        
        Args:
            entry_price: Entry price
            atr: Average True Range
            multiplier: ATR multiplier (default from config or trade type)
            trade_type: "swing" or "intraday"
        
        Returns:
            Stop loss price
        """
        if multiplier is None:
            if trade_type == "intraday":
                multiplier = 1.0
            else:
                multiplier = config.get("risk.atr_multiplier", 1.5)
        
        stop_loss = entry_price - (atr * multiplier)
        return max(0, stop_loss)  # Ensure non-negative
    
    @staticmethod
    def calculate_support_based_stop(df: pd.DataFrame, entry_price: float) -> Optional[float]:
        """
        Calculate stop loss based on nearest support level.
        
        Args:
            df: OHLCV DataFrame
            entry_price: Entry price
        
        Returns:
            Support-based stop loss or None if not found
        """
        if df.empty or len(df) < 20:
            return None
        
        # Find recent swing lows (support levels)
        lows = df['low'].tail(50)
        
        # Find local minima
        support_levels = []
        for i in range(2, len(lows) - 2):
            if (lows.iloc[i] < lows.iloc[i-1] and 
                lows.iloc[i] < lows.iloc[i-2] and
                lows.iloc[i] < lows.iloc[i+1] and
                lows.iloc[i] < lows.iloc[i+2]):
                support_levels.append(lows.iloc[i])
        
        if not support_levels:
            return None
        
        # Find nearest support below entry price
        supports_below = [s for s in support_levels if s < entry_price]
        if not supports_below:
            return None
        
        # Return highest support below entry (nearest)
        nearest_support = max(supports_below)
        
        # Place stop slightly below support (0.5% buffer)
        stop_loss = nearest_support * 0.995
        return stop_loss
    
    @staticmethod
    def calculate_optimal_stop_loss(
        entry_price: float,
        atr: float,
        df: Optional[pd.DataFrame] = None,
        volume_profile: Optional[Dict] = None,
        trade_type: str = "swing",
        atr_multiplier: Optional[float] = None
    ) -> Dict:
        """
        Calculate optimal stop loss using both ATR and support levels.
        
        Per spec Section 7.2:
        - "Support-Based Stop: SL placed below nearest significant support level"
        - "Final SL Selection: The system picks the tighter of ATR-based and support-based"
        
        The TIGHTER stop (higher price) is selected as it results in:
        - Less risk per share
        - Better risk/reward ratio
        - Smaller position size but tighter control
        
        Args:
            entry_price: Entry price
            atr: Average True Range (14-period)
            df: OHLCV DataFrame for support detection
            volume_profile: Optional volume profile for VAL/POC support
            trade_type: "swing" or "intraday"
            atr_multiplier: Override ATR multiplier
            
        Returns:
            Dict with:
                - 'stop_loss': float - the final (tighter) stop loss
                - 'method': str - which method produced the final stop
                - 'atr_stop': float - ATR-based stop
                - 'support_stop': float|None - support-based stop
                - 'volume_profile_stop': float|None - volume profile stop
        """
        result = {
            'stop_loss': None,
            'method': 'atr',
            'atr_stop': None,
            'support_stop': None,
            'volume_profile_stop': None
        }
        
        # Method 1: ATR-based stop
        atr_stop = RiskManager.calculate_stop_loss(
            entry_price, atr, 
            multiplier=atr_multiplier, 
            trade_type=trade_type
        )
        result['atr_stop'] = atr_stop
        
        # Start with ATR stop as default
        final_stop = atr_stop
        method = 'atr'
        
        # Method 2: Support-based stop (from price action)
        if df is not None and not df.empty:
            support_stop = RiskManager.calculate_support_based_stop(df, entry_price)
            if support_stop is not None:
                result['support_stop'] = support_stop
                
                # Use support stop if tighter (higher price = less risk)
                if support_stop > final_stop:
                    final_stop = support_stop
                    method = 'support'
        
        # Method 3: Volume Profile stop (VAL or POC as support)
        if volume_profile:
            val = volume_profile.get('value_area_low')
            poc = volume_profile.get('poc_price')
            
            # Use VAL or POC as support, whichever is closer below entry
            vp_candidates = [v for v in [val, poc] if v is not None and v < entry_price]
            if vp_candidates:
                vp_support = max(vp_candidates)  # Closest below entry
                vp_stop = vp_support * 0.995  # 0.5% below support
                result['volume_profile_stop'] = vp_stop
                
                # Use VP stop if tighter
                if vp_stop > final_stop:
                    final_stop = vp_stop
                    method = 'volume_profile'
        
        result['stop_loss'] = final_stop
        result['method'] = method
        
        logger.debug(
            f"Stop loss calculated: ${final_stop:.2f} ({method}) | "
            f"ATR: ${atr_stop:.2f}, Support: {result['support_stop']}, VP: {result['volume_profile_stop']}"
        )
        
        return result
    
    @staticmethod
    def calculate_position_size(
        entry_price: float,
        stop_loss: float,
        risk_amount: Optional[float] = None,
        include_commissions: bool = True
    ) -> Tuple[int, float, Dict]:
        """
        Calculate position size based on risk.
        
        Per spec: Position = (Equity × 2%) / (Entry - Stop Loss)
        
        Integrates with DrawdownProtection to reduce risk during losing streaks.
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            risk_amount: Maximum risk per trade (€)
            include_commissions: Whether to account for broker commissions
        
        Returns:
            Tuple of (quantity, actual_risk, metadata_dict)
        """
        # Get user database
        if RiskManager._user_db is None:
            from ..database.user_db import UserDatabase
            RiskManager._user_db = UserDatabase()
        
        user_db = RiskManager._user_db
        
        # Get drawdown protection status
        protection = RiskManager.get_drawdown_protection()
        protection_status = protection.get_protection_status()
        risk_multiplier = protection_status.get('risk_multiplier', 1.0)
        
        # Determine risk amount
        if risk_amount is None:
            risk_use_fixed_str = user_db.get_setting("risk_use_fixed")
            if risk_use_fixed_str is not None:
                use_fixed = risk_use_fixed_str.lower() == "true"
            else:
                use_fixed = config.get("risk.use_fixed_risk", True)
            
            if use_fixed:
                risk_fixed_str = user_db.get_setting("risk_fixed_amount")
                if risk_fixed_str is not None:
                    risk_amount = float(risk_fixed_str)
                else:
                    risk_amount = config.get("risk.max_risk_per_trade_fixed", 100)
            else:
                # Calculate from percentage of capital (spec: 2% max)
                # Priority: portfolio_total_capital > available_capital > config
                capital_str = user_db.get_setting("portfolio_total_capital")
                if capital_str is None:
                    capital_str = user_db.get_setting("available_capital")
                if capital_str is None:
                    capital = config.get("risk.available_capital", 10000)
                else:
                    capital = float(capital_str)
                
                risk_percent_str = user_db.get_setting("risk_percent")
                if risk_percent_str is not None:
                    risk_percent = float(risk_percent_str)
                else:
                    risk_percent = config.get("risk.max_risk_per_trade_percent", 2.0)
                
                risk_amount = capital * (risk_percent / 100)
        
        # Apply drawdown protection risk reduction
        adjusted_risk = risk_amount * risk_multiplier
        
        if entry_price <= stop_loss:
            logger.warning("Stop loss >= Entry price. Cannot calculate position size.")
            return 0, 0, {'commission_cost': 0, 'net_risk': 0, 'min_profit_needed': 0, 'risk_multiplier': risk_multiplier}
        
        # Get commission settings
        commission_per_trade = config.get("risk.commission_per_trade", 1.0)  # €1 per Trade Republic
        min_trade_value = config.get("risk.min_trade_value", 50.0)
        min_profit_after_comm = config.get("risk.min_profit_after_commissions", 5.0)
        
        # Exchange rate
        rate = get_exchange_rate(user_db=user_db, config=config)
        risk_per_share_usd = entry_price - stop_loss
        
        # Sizing method
        sizing_method = (user_db.get_setting("sizing_method") or config.get("risk.sizing_method", "risk_based")).lower().strip()
        if sizing_method not in ("slots", "risk_based"):
            sizing_method = "risk_based"
        
        slot_value_eur = None
        if sizing_method == "slots":
            # Slot-based sizing
            capital_str = user_db.get_setting("available_capital")
            capital = float(capital_str) if capital_str else config.get("risk.available_capital", 1500)
            slots_str = user_db.get_setting("slots_count")
            slots_count = max(1, int(slots_str)) if slots_str else max(1, int(config.get("risk.slots_count", 3)))
            slot_value_eur = capital / slots_count
            quantity = int((slot_value_eur / rate) / entry_price) if entry_price > 0 else 0
        else:
            # Risk-based sizing (per spec formula)
            risk_per_share_eur = risk_per_share_usd * rate
            quantity = int(adjusted_risk / risk_per_share_eur) if risk_per_share_eur > 0 else 0
        
        if quantity <= 0:
            return 0, 0, {'commission_cost': 0, 'net_risk': 0, 'min_profit_needed': 0, 'risk_multiplier': risk_multiplier}
        
        # Check max position value (33% of equity per spec)
        # Priority: portfolio_total_capital > available_capital > config
        capital_str = user_db.get_setting("portfolio_total_capital")
        if not capital_str:
            capital_str = user_db.get_setting("available_capital")
        capital = float(capital_str) if capital_str else config.get("risk.available_capital", 10000)
        max_position_value_usd = (capital / rate) * 0.33  # 33% of equity
        
        position_value = entry_price * quantity
        if position_value > max_position_value_usd:
            quantity = int(max_position_value_usd / entry_price)
            logger.debug(f"Position size capped to 33% of equity: {quantity} shares")
        
        if quantity <= 0:
            return 0, 0, {'commission_cost': 0, 'net_risk': 0, 'min_profit_needed': 0, 'risk_multiplier': risk_multiplier}
        
        # Calculate costs and risk
        total_commission = commission_per_trade * 2  # Entry + Exit
        actual_risk_usd = quantity * risk_per_share_usd
        actual_risk_eur = actual_risk_usd * rate
        net_risk = actual_risk_eur + total_commission
        
        min_profit_needed = total_commission + min_profit_after_comm
        
        trade_value_usd = entry_price * quantity
        trade_value_eur = trade_value_usd * rate
        commission_percent = (total_commission / trade_value_eur * 100) if trade_value_eur > 0 else 100
        
        metadata = {
            'commission_cost': total_commission,
            'net_risk': net_risk,
            'min_profit_needed': min_profit_needed,
            'trade_value': trade_value_usd,
            'commission_percent': commission_percent,
            'is_profitable_after_commissions': commission_percent < 2.0 and trade_value_eur >= min_trade_value,
            'sizing_method': sizing_method,
            'risk_multiplier': risk_multiplier,
            'original_risk': risk_amount,
            'adjusted_risk': adjusted_risk
        }
        
        if slot_value_eur is not None:
            metadata['slot_value_eur'] = slot_value_eur
        
        return quantity, actual_risk_eur, metadata
    
    @staticmethod
    def calculate_trailing_stop(current_price: float, atr: float,
                                highest_price: float, entry_price: float,
                                multiplier: Optional[float] = None) -> Tuple[float, bool]:
        """
        Calculate trailing stop loss.
        
        Per spec: Once trade is in profit by 1× ATR, trail at 1.5× ATR below highest price.
        
        Args:
            current_price: Current price
            atr: Average True Range
            highest_price: Highest price since entry
            entry_price: Original entry price
            multiplier: ATR multiplier (default 1.5)
        
        Returns:
            Tuple of (trailing_stop_price, should_activate)
        """
        if multiplier is None:
            multiplier = config.get("risk.atr_multiplier", 1.5)
        
        # Check if trailing should activate (1× ATR profit)
        profit = highest_price - entry_price
        should_activate = profit >= atr
        
        if not should_activate:
            return entry_price - (atr * multiplier), False
        
        # Calculate trailing stop
        trailing_stop = highest_price - (atr * multiplier)
        
        # Don't trail below entry (breakeven minimum after activation)
        trailing_stop = max(trailing_stop, entry_price)
        
        return trailing_stop, True
    
    @staticmethod
    def calculate_target_price(
        entry_price: float,
        stop_loss: float,
        atr: float,
        volume_profile: Optional[Dict] = None,
        method: str = "risk_reward"
    ) -> Optional[float]:
        """
        Calculate target price for take profit.
        
        Per spec:
        - TP1: Entry + 1.5× ATR (partial exit, 50%)
        - TP2: Entry + 3× ATR (full exit)
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            atr: Average True Range
            volume_profile: Volume profile dict with resistance levels
            method: Calculation method
        
        Returns:
            Target price or None
        """
        if entry_price <= stop_loss:
            return None
        
        risk_per_share = entry_price - stop_loss
        
        if method == "risk_reward":
            # Risk/Reward ratio method (default 2:1)
            reward_ratio = config.get("risk.target_reward_ratio", 2.0)
            target = entry_price + (risk_per_share * reward_ratio)
            return target
        
        elif method == "atr_multiple":
            # ATR multiple method
            target_multiplier = config.get("risk.target_atr_multiplier", 3.0)
            if atr and atr > 0:
                target = entry_price + (atr * target_multiplier)
                return target
            return None
        
        elif method == "volume_profile":
            # Volume Profile resistance method
            if volume_profile:
                vah = volume_profile.get('value_area_high')
                if vah and vah > entry_price:
                    return vah
                # Fallback to ATR method
                if atr and atr > 0:
                    return entry_price + (atr * 3.0)
            return None
        
        return None
    
    @staticmethod
    def calculate_partial_exits(entry_price: float, atr: float) -> Dict:
        """
        Calculate partial exit levels per spec.
        
        TP1: Entry + 1.5× ATR → Sell 50%, move SL to breakeven
        TP2: Entry + 3× ATR → Close remaining
        
        Returns:
            Dict with tp1, tp2 prices and actions
        """
        tp1 = entry_price + (1.5 * atr)
        tp2 = entry_price + (3.0 * atr)
        
        return {
            'tp1': {
                'price': tp1,
                'action': 'Sell 50%, move SL to breakeven',
                'pct_of_position': 0.5
            },
            'tp2': {
                'price': tp2,
                'action': 'Close remaining position',
                'pct_of_position': 1.0  # Remaining 50%
            },
            'breakeven': entry_price
        }
    
    @staticmethod
    def validate_risk_reward_ratio(entry_price: float, stop_loss: float, 
                                   target_price: float, min_ratio: float = 2.0) -> Dict:
        """
        Validate that trade meets minimum risk/reward ratio.
        
        Per spec: If no setup achieves 2:1, the trade is rejected.
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            target_price: Target price
            min_ratio: Minimum required R:R ratio (default 2.0)
        
        Returns:
            Dict with validation result
        """
        if entry_price <= stop_loss:
            return {
                'is_valid': False,
                'ratio': 0,
                'reason': 'Stop loss must be below entry price'
            }
        
        if target_price <= entry_price:
            return {
                'is_valid': False,
                'ratio': 0,
                'reason': 'Target must be above entry price'
            }
        
        risk = entry_price - stop_loss
        reward = target_price - entry_price
        ratio = reward / risk if risk > 0 else 0
        
        is_valid = ratio >= min_ratio
        
        return {
            'is_valid': is_valid,
            'ratio': round(ratio, 2),
            'risk': risk,
            'reward': reward,
            'reason': f"R:R ratio {ratio:.2f}:1 {'meets' if is_valid else 'below'} minimum {min_ratio}:1"
        }
