"""
Telegram Bot for Trading Alerts
Per Trading System Specification v1.0 Section 8.2

Alert Types:
- Strong Signal (80+): Telegram + Dashboard - Immediate notification
- SL Approaching (within 0.5%): Telegram - Urgent warning
- TP Hit: Telegram + Dashboard - Action required
- Risk Limit Breach: Telegram (urgent) - Critical alert
- Daily Summary: Email (optional)
"""
from telegram import Bot
from telegram.error import TelegramError
from typing import Dict, Optional, List
from loguru import logger
import asyncio
from datetime import datetime

from ..utils.config import config


class TelegramNotifier:
    """Send alerts via Telegram with score-based priority"""
    
    # Alert priority levels
    PRIORITY_CRITICAL = "🚨"  # Risk breaches
    PRIORITY_HIGH = "🔔"      # Strong signals (80+)
    PRIORITY_MEDIUM = "📢"    # Moderate signals (65-79)
    PRIORITY_LOW = "📝"       # Weak signals, updates
    
    def __init__(self):
        self.bot_token = config.get_env("TELEGRAM_BOT_TOKEN")
        self.chat_id = config.get_env("TELEGRAM_CHAT_ID")
        self.enabled = config.get("telegram.enabled", True)
        self._bot = None
        
        if not self.bot_token or not self.chat_id:
            logger.debug("Telegram credentials not configured. Notifications disabled.")
            self.enabled = False
        else:
            self.enabled = True
    
    @property
    def bot(self):
        """Lazy initialization of bot"""
        if self._bot is None and self.enabled:
            try:
                self._bot = Bot(token=self.bot_token)
            except Exception as e:
                logger.error(f"Failed to initialize Telegram bot: {e}")
                self.enabled = False
        return self._bot
    
    async def send_message(self, message: str, urgent: bool = False) -> bool:
        """Send a message to Telegram"""
        if not self.enabled or not self.bot:
            return False
        
        try:
            # Use a timeout to avoid hanging
            await asyncio.wait_for(
                self.bot.send_message(
                    chat_id=self.chat_id, 
                    text=message, 
                    parse_mode='HTML',
                    disable_notification=not urgent  # Only notify for urgent messages
                ),
                timeout=10.0
            )
            return True
        except asyncio.TimeoutError:
            logger.warning("Telegram send timeout - message not sent")
            return False
        except TelegramError as e:
            if "Not Found" in str(e) or "Unauthorized" in str(e):
                logger.debug(f"Telegram not configured or invalid credentials: {e}")
            elif "Pool timeout" in str(e):
                logger.warning(f"Telegram pool timeout - too many concurrent requests.")
            elif "Event loop is closed" in str(e):
                logger.warning(f"Telegram event loop error - message not sent")
            else:
                logger.error(f"Telegram error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected Telegram error: {e}")
            return False
    
    def _get_score_classification(self, score: float) -> tuple:
        """Get score classification and emoji based on 100-point scale"""
        if score >= 80:
            return "STRONG", "🟢", self.PRIORITY_HIGH
        elif score >= 65:
            return "MODERATE", "🔵", self.PRIORITY_MEDIUM
        elif score >= 50:
            return "WEAK", "⚪", self.PRIORITY_LOW
        else:
            return "NO_SIGNAL", "🔴", self.PRIORITY_LOW
    
    async def send_signal_alert(self, signal: Dict) -> bool:
        """
        Send signal alert with score-based priority.
        Per spec: Strong signals (80+) get immediate alert.
        """
        if not config.get("telegram.alert_on_signal", True):
            return False
        
        symbol = signal['symbol']
        score = signal.get('score', 0)
        price = signal.get('current_price', signal.get('entry_price', 0))
        entry = signal.get('entry_price', 0)
        stop = signal.get('stop_loss', 0)
        target = signal.get('target_price')
        tp1 = signal.get('tp1')
        tp2 = signal.get('tp2')
        size = signal.get('position_size', 0)
        risk = signal.get('risk_amount', 0)
        
        # Get classification based on score
        classification, emoji, priority = self._get_score_classification(score)
        
        # Only send alerts for signals >= 50 (per spec: 0-49 is NO_SIGNAL)
        if score < 50:
            logger.debug(f"Signal {symbol} score {score} too low for alert")
            return False
        
        # Determine urgency - Strong signals (80+) are urgent
        urgent = score >= 80
        
        message = f"""
{priority} <b>Trading Signal - {classification}</b>

{emoji} <b>{symbol}</b>
📊 Score: <b>{score}/100</b> ({classification})

💰 Current Price: ${price:.2f}
🎯 Entry: ${entry:.2f}
🛑 Stop Loss: ${stop:.2f}
"""
        
        if tp1 and tp2:
            message += f"""
📈 <b>Take Profit Targets:</b>
• TP1: ${tp1:.2f} (sell 50%, move SL to breakeven)
• TP2: ${tp2:.2f} (close remaining)
"""
        elif target:
            message += f"🎯 Target: ${target:.2f}\n"
        
        message += f"""
📦 Position Size: {size} shares
⚠️ Risk: €{risk:.2f}

<i>Execute via Trade Republic - Use LIMIT order</i>
"""
        
        return await self.send_message(message, urgent=urgent)
    
    async def send_price_alert(self, symbol: str, price: float, level_type: str,
                               entry_price: float = None, stop_loss: float = None) -> bool:
        """
        Send price level alert.
        Per spec: SL approaching (within 0.5%) gets Telegram alert.
        """
        if not config.get("telegram.alert_on_price_level", True):
            return False
        
        urgent = False
        
        if level_type == "target_reached":
            emoji = "🎯"
            action = "TARGET REACHED"
            details = "Consider taking profits!"
            urgent = True
        elif level_type == "tp1_reached":
            emoji = "🎯"
            action = "TP1 REACHED"
            details = "Sell 50%, move stop to breakeven!"
            urgent = True
        elif level_type == "tp2_reached":
            emoji = "🏆"
            action = "TP2 REACHED"
            details = "Close remaining position - Full profit!"
            urgent = True
        elif level_type == "stop_loss":
            emoji = "🛑"
            action = "STOP LOSS HIT"
            details = "Position should be closed"
            urgent = True
        elif level_type == "stop_approaching":
            emoji = "⚠️"
            action = "STOP LOSS APPROACHING"
            distance_pct = ((price - stop_loss) / stop_loss * 100) if stop_loss else 0
            details = f"Price within {abs(distance_pct):.1f}% of stop"
            urgent = True
        elif level_type == "entry_reached":
            emoji = "✅"
            action = "ENTRY PRICE REACHED"
            details = "Execute trade now!"
            urgent = True
        else:
            emoji = "🔔"
            action = f"PRICE ALERT: {level_type}"
            details = ""
        
        message = f"""
{emoji} <b>{action}</b>

<b>{symbol}</b>
Current Price: ${price:.2f}
{details}
"""
        
        if entry_price:
            pnl_pct = ((price - entry_price) / entry_price) * 100
            message += f"\nP&L: {pnl_pct:+.1f}%"
        
        return await self.send_message(message, urgent=urgent)
    
    async def send_stop_update(self, symbol: str, old_stop: float, new_stop: float,
                               reason: str = "Trailing stop") -> bool:
        """Send trailing stop update notification"""
        if not config.get("telegram.alert_on_stop_update", True):
            return False
        
        improvement = ((new_stop - old_stop) / old_stop) * 100
        
        message = f"""
🔄 <b>Stop Loss Updated</b>

<b>{symbol}</b>
Old Stop: ${old_stop:.2f}
New Stop: ${new_stop:.2f}
Improvement: {improvement:+.1f}%

Reason: {reason}
"""
        
        return await self.send_message(message, urgent=False)
    
    async def send_risk_breach_alert(self, breach_type: str, details: Dict) -> bool:
        """
        Send urgent risk breach notification.
        Per spec: Risk limit breaches get urgent Telegram alerts.
        """
        if not self.enabled:
            return False
        
        if breach_type == "consecutive_losses":
            count = details.get('count', 0)
            action = details.get('action', '')
            
            message = f"""
{self.PRIORITY_CRITICAL} <b>RISK ALERT: Consecutive Losses</b>

⚠️ {count} consecutive losing trades detected

<b>Action Taken:</b>
{action}

<i>Review your recent trades and consider taking a break.</i>
"""
        
        elif breach_type == "monthly_drawdown":
            drawdown = details.get('drawdown_percent', 0)
            threshold = details.get('threshold', 0)
            action = details.get('action', '')
            
            if drawdown >= 10:
                severity = "CRITICAL"
            elif drawdown >= 6:
                severity = "WARNING"
            else:
                severity = "NOTICE"
            
            message = f"""
{self.PRIORITY_CRITICAL} <b>RISK ALERT: Monthly Drawdown - {severity}</b>

📉 Drawdown: {drawdown:.1f}%
⚠️ Threshold: {threshold:.1f}%

<b>Action:</b>
{action}

<i>Protect your capital - review strategy before continuing.</i>
"""
        
        elif breach_type == "position_limit":
            current = details.get('current_positions', 0)
            max_allowed = details.get('max_allowed', 0)
            
            message = f"""
{self.PRIORITY_CRITICAL} <b>RISK ALERT: Position Limit</b>

📊 Current positions: {current}
⚠️ Maximum allowed: {max_allowed}

<b>Action Required:</b>
Close existing positions before opening new ones.
"""
        
        elif breach_type == "exposure_limit":
            exposure = details.get('exposure_percent', 0)
            max_exposure = details.get('max_exposure', 90)
            
            message = f"""
{self.PRIORITY_CRITICAL} <b>RISK ALERT: Exposure Limit</b>

📊 Current exposure: {exposure:.1f}%
⚠️ Maximum recommended: {max_exposure:.1f}%

<b>Recommendation:</b>
Consider reducing position sizes or closing some positions.
"""
        
        else:
            message = f"""
{self.PRIORITY_CRITICAL} <b>RISK ALERT</b>

Type: {breach_type}
Details: {details}

<i>Review immediately.</i>
"""
        
        return await self.send_message(message, urgent=True)
    
    async def send_daily_summary(self, summary: Dict) -> bool:
        """
        Send daily trading summary.
        Per spec: End-of-day report with P&L, open positions, tomorrow watchlist.
        """
        if not self.enabled:
            return False
        
        date = summary.get('date', datetime.now().strftime('%Y-%m-%d'))
        total_pnl = summary.get('total_pnl', 0)
        open_positions = summary.get('open_positions', 0)
        trades_today = summary.get('trades_today', 0)
        wins = summary.get('wins', 0)
        losses = summary.get('losses', 0)
        watchlist = summary.get('watchlist', [])
        
        pnl_emoji = "📈" if total_pnl >= 0 else "📉"
        
        message = f"""
📊 <b>Daily Trading Summary - {date}</b>

{pnl_emoji} <b>P&L Today:</b> €{total_pnl:+.2f}

📋 <b>Activity:</b>
• Trades: {trades_today}
• Wins: {wins}
• Losses: {losses}
• Open Positions: {open_positions}
"""
        
        if watchlist:
            message += f"""
🎯 <b>Tomorrow's Watchlist:</b>
"""
            for symbol in watchlist[:5]:  # Max 5 symbols
                message += f"• {symbol}\n"
        
        message += """
<i>Good trading! Review and prepare for tomorrow.</i>
"""
        
        return await self.send_message(message, urgent=False)
