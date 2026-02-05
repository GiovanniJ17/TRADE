"""
Streamlit Dashboard V2 - Complete Autonomous Trading System
Integrates Portfolio Manager with multi-strategy approach
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dss.core.portfolio_manager import PortfolioManager
from dss.database.market_db import MarketDatabase
from dss.database.user_db import UserDatabase
from dss.intelligence.indicators import IndicatorCalculator
from dss.intelligence.risk_manager import DrawdownProtection, RiskManager
from dss.utils.config import config
from dss.utils.logger import logger
from dss.utils.market_hours import get_market_status

# Page configuration
st.set_page_config(
    page_title="Trading System DSS - Multi-Strategy",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'portfolio_mgr' not in st.session_state:
    st.session_state.portfolio_mgr = PortfolioManager()
if 'market_db' not in st.session_state:
    st.session_state.market_db = MarketDatabase()
if 'user_db' not in st.session_state:
    st.session_state.user_db = UserDatabase()
if 'signals' not in st.session_state:
    st.session_state.signals = None
if 'last_update' not in st.session_state:
    st.session_state.last_update = None

# Auto-refresh exchange rate on startup (once per session)
if 'exchange_rate_refreshed' not in st.session_state:
    try:
        from dss.utils.currency import get_exchange_rate, _fetch_exchange_rate_from_api
        fresh_rate = _fetch_exchange_rate_from_api()
        if fresh_rate:
            st.session_state.user_db.set_setting("cached_exchange_rate", str(fresh_rate))
            from datetime import datetime
            st.session_state.user_db.set_setting("cached_exchange_rate_timestamp", datetime.now().isoformat())
            logger.info(f"Auto-refreshed exchange rate: 1 USD = {fresh_rate:.4f} EUR")
        st.session_state.exchange_rate_refreshed = True
    except Exception as e:
        logger.warning(f"Could not auto-refresh exchange rate: {e}")
        st.session_state.exchange_rate_refreshed = True


def _get_data_freshness_status():
    """Get data freshness status for badge display (QoL 1.1)"""
    try:
        # Get last data timestamp from SPY (benchmark) or AAPL as fallback
        spy_data = st.session_state.market_db.get_data('SPY')
        if spy_data.empty:
            # Fallback to AAPL if SPY not available
            spy_data = st.session_state.market_db.get_data('AAPL')
        if spy_data.empty:
            return {'badge': '🔴', 'text': 'Nessun dato', 'is_stale': True}
        
        # Get timestamp from 'timestamp' column, not index
        last_timestamp = spy_data['timestamp'].iloc[-1]
        last_date = pd.to_datetime(last_timestamp).date()
        today = datetime.now().date()
        days_old = (today - last_date).days
        
        # Debug logging
        logger.debug(f"Data freshness check: last_timestamp={last_timestamp}, last_date={last_date}, today={today}, days_old={days_old}")
        
        # Account for weekends - if today is Monday, data from Friday is OK (1 trading day old)
        # If today is weekend, data from Friday is current
        today_weekday = today.weekday()
        last_weekday = last_date.weekday()
        
        # Calculate trading days difference (excluding weekends)
        trading_days_old = days_old
        if days_old > 0:
            # Subtract weekend days between last_date and today
            current = last_date
            weekend_days = 0
            for i in range(days_old):
                current = last_date + pd.Timedelta(days=i+1)
                if current.weekday() >= 5:  # Saturday=5, Sunday=6
                    weekend_days += 1
            trading_days_old = days_old - weekend_days
        
        if trading_days_old <= 0:
            return {'badge': '🟢', 'text': 'Dati aggiornati', 'is_stale': False}
        elif trading_days_old == 1:
            return {'badge': '🟡', 'text': f'Dati di ieri ({last_date})', 'is_stale': False}
        else:
            return {'badge': '🔴', 'text': f'Dati vecchi ({trading_days_old} giorni, ultimo: {last_date})', 'is_stale': True}
    except Exception as e:
        logger.error(f"Error checking data freshness: {e}")
        return {'badge': '⚪', 'text': 'Stato dati sconosciuto', 'is_stale': True}


def _get_trailing_stop_suggestion(pos: dict, current_price: float, pnl_pct: float) -> str:
    """Generate trailing stop suggestion based on profit level (QoL 2.1)
    
    Suggests raising stop-loss to lock in profits when position is in significant profit.
    """
    if pnl_pct < 5:
        return None  # No suggestion if profit is less than 5%
    
    entry_price = pos.get('entry_price', 0)
    current_stop = pos.get('current_stop_loss') or pos.get('stop_loss')
    
    if not entry_price or not current_stop:
        return None
    
    # Calculate suggested trailing stop based on profit level
    if pnl_pct >= 15:
        # Large profit: suggest locking in 10% of gain
        suggested_stop = entry_price * 1.10
        suggestion = f"💡 **Trailing Stop Suggerito**: Con +{pnl_pct:.1f}% di profitto, considera di alzare lo stop a {_fmt_usd(suggested_stop)} per bloccare almeno +10% di guadagno."
    elif pnl_pct >= 10:
        # Good profit: suggest moving to breakeven + small profit
        suggested_stop = entry_price * 1.05
        suggestion = f"💡 **Trailing Stop Suggerito**: Con +{pnl_pct:.1f}% di profitto, considera di alzare lo stop a {_fmt_usd(suggested_stop)} per bloccare +5% di guadagno."
    elif pnl_pct >= 5:
        # Moderate profit: suggest moving to breakeven
        suggested_stop = entry_price * 1.01
        suggestion = f"💡 **Trailing Stop Suggerito**: Con +{pnl_pct:.1f}% di profitto, considera di alzare lo stop a breakeven ({_fmt_usd(suggested_stop)}) per proteggere il capitale."
    else:
        return None
    
    # Only show if current stop is below suggested
    if current_stop >= suggested_stop:
        return None
    
    return suggestion


def _render_workflow_checklist(market_status: dict, positions: list):
    """Render dynamic workflow checklist (QoL 1.3)
    
    Shows what needs to be done today based on current system state.
    """
    from datetime import datetime
    
    today = datetime.now()
    day_name_it = {
        0: 'Lunedì', 1: 'Martedì', 2: 'Mercoledì',
        3: 'Giovedì', 4: 'Venerdì', 5: 'Sabato', 6: 'Domenica'
    }
    month_name_it = {
        1: 'Gen', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mag', 6: 'Giu',
        7: 'Lug', 8: 'Ago', 9: 'Set', 10: 'Ott', 11: 'Nov', 12: 'Dic'
    }
    
    day_str = day_name_it.get(today.weekday(), 'N/A')
    month_str = month_name_it.get(today.month, 'N/A')
    
    st.subheader(f"📋 Workflow di oggi ({day_str} {today.day} {month_str})")
    
    checklist_items = []
    
    # 1. Market Status Check
    market_open = market_status['status'] in ['open', 'pre-market', 'after-hours']
    if market_status['status'] == 'open':
        checklist_items.append(('✅', 'Mercato', 'Aperto — Regular Session'))
    elif market_status['status'] == 'pre-market':
        checklist_items.append(('🟡', 'Mercato', 'Pre-Market'))
    elif market_status['status'] == 'after-hours':
        checklist_items.append(('🟡', 'Mercato', 'After-Hours'))
    else:
        reason = market_status.get('reason', 'Weekend')
        checklist_items.append(('🔴', 'Mercato', f'Chiuso ({reason})'))
    
    # 2. Data Freshness Check
    data_status = _get_data_freshness_status()
    if data_status['is_stale']:
        checklist_items.append(('⬜', 'Dati aggiornati', f"No — {data_status['text']}"))
    else:
        checklist_items.append(('✅', 'Dati aggiornati', f"Sì — {data_status['text']}"))
    
    # 3. Signals Generated Check
    signals = st.session_state.get('signals')
    if signals and len(signals.get('stock_signals', [])) > 0:
        num_signals = len(signals.get('stock_signals', []))
        checklist_items.append(('✅', 'Segnali generati', f"Sì — {num_signals} segnali attivi"))
    else:
        checklist_items.append(('⬜', 'Segnali generati', 'No'))
    
    # 4. Positions to Monitor
    if positions:
        checklist_items.append(('⬜', 'Posizioni controllate', f"{len(positions)} aperte"))
    else:
        checklist_items.append(('✅', 'Posizioni', 'Nessuna posizione aperta'))
    
    # Render checklist
    for icon, label, value in checklist_items:
        st.markdown(f"{icon} **{label}:** {value}")
    
    # Action buttons based on state
    st.markdown("")  # Spacer
    
    col1, col2 = st.columns(2)
    
    with col1:
        if data_status['is_stale']:
            if st.button("📥 Aggiorna Dati", key="workflow_update", type="primary"):
                update_market_data()
    
    with col2:
        if not signals or len(signals.get('stock_signals', [])) == 0:
            if not data_status['is_stale']:
                if st.button("🔄 Genera Segnali", key="workflow_signals", type="primary"):
                    with st.spinner("🧠 Analyzing..."):
                        try:
                            portfolio_mgr = st.session_state.portfolio_mgr
                            portfolio_mgr.reload_settings()
                            new_signals = portfolio_mgr.generate_portfolio_signals()
                            st.session_state.signals = new_signals
                            st.rerun()
                        except Exception as e:
                            st.error(f"Errore: {e}")
        elif positions:
            if st.button("💼 Controlla Posizioni", key="workflow_positions"):
                st.session_state.navigate_to = "💼 My Positions"
                st.rerun()


def _fmt_usd(amount_usd):
    """Format USD amount for display"""
    if amount_usd is None:
        return "N/A"
    try:
        return f"${float(amount_usd):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_eur(amount_eur):
    """Format EUR amount for display"""
    if amount_eur is None:
        return "N/A"
    try:
        return f"€{float(amount_eur):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def reload_portfolio_manager():
    """Force reload of portfolio manager with new settings"""
    if 'portfolio_mgr' in st.session_state:
        del st.session_state['portfolio_mgr']
    st.session_state.portfolio_mgr = PortfolioManager()
    logger.info("Portfolio Manager reloaded with new settings")


def update_market_data():
    """Update market data from Polygon.io"""
    try:
        from dss.ingestion.update_data import DataUpdater
        
        # Create progress placeholder
        progress_text = st.empty()
        progress_bar = st.progress(0)
        
        progress_text.text("📥 Connecting to Polygon.io...")
        progress_bar.progress(10)
        
        # Create updater and load watchlist
        updater = DataUpdater()
        symbols = updater.load_watchlist()
        
        progress_text.text(f"📊 Loading watchlist ({len(symbols)} symbols)...")
        progress_bar.progress(20)
        
        # Run update with proper cleanup
        progress_text.text("⬇️ Downloading market data (this may take 30-60 seconds)...")
        progress_bar.progress(30)
        
        # Use async context to ensure cleanup
        async def run_update():
            try:
                await updater.update_all()
            finally:
                await updater.close()  # IMPORTANT: Close HTTP connections
        
        asyncio.run(run_update())
        
        progress_bar.progress(100)
        progress_text.empty()
        progress_bar.empty()
        
        st.session_state.last_update = datetime.now()
        st.success(f"✅ Market data updated successfully! ({len(symbols)} symbols)")
        st.info("💡 Data is now up-to-date. You can generate new signals.")
        return True
        
    except Exception as e:
        st.error(f"❌ Error updating data: {e}")
        logger.error(f"Data update error: {e}", exc_info=True)
        
        # Helpful error messages
        error_str = str(e)
        if "api" in error_str.lower() or "key" in error_str.lower():
            st.warning("⚠️ Check your Polygon.io API key in .env file")
        elif "network" in error_str.lower() or "connection" in error_str.lower():
            st.warning("⚠️ Check your internet connection")
        elif "rate" in error_str.lower() or "limit" in error_str.lower():
            st.warning("⚠️ API rate limit reached. Wait a few minutes and try again.")
        
        return False


def main():
    """Main dashboard"""
    # Header
    st.title("🎯 Trading System DSS - Multi-Strategy")
    st.markdown("**Autonomous Decision Support System for Swing Trading**")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Quick Actions")
        
        # Data Status Badge (QoL 1.1)
        data_status = _get_data_freshness_status()
        st.markdown(f"{data_status['badge']} {data_status['text']}")
        
        # Update Data Button
        if st.button("📥 Update Market Data", type="primary", width="stretch"):
            update_market_data()
        
        if st.session_state.last_update:
            st.caption(f"Last update: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M')}")
        
        st.divider()
        
        # Stale Data Warning (QoL 4.1)
        if data_status['is_stale']:
            st.warning(f"⚠️ I dati di mercato potrebbero essere vecchi. Aggiorna prima di generare segnali.")
        
        # Generate Signals Button
        if st.button("🔄 Generate Signals", type="primary", width="stretch"):
            with st.spinner("🧠 Analyzing market and generating signals..."):
                try:
                    # IMPORTANT: Reload settings from database before generating signals
                    # This ensures we use the latest user settings, not cached values
                    portfolio_mgr = st.session_state.portfolio_mgr
                    portfolio_mgr.reload_settings()
                    
                    signals = portfolio_mgr.generate_portfolio_signals()
                    st.session_state.signals = signals
                    
                    # Show quick summary
                    stock_count = len(signals.get('stock_signals', []))
                    regime = signals.get('regime', {}).get('regime', 'Unknown').upper()
                    
                    st.success(f"✅ Analysis complete! {stock_count} signals found (Regime: {regime})")
                    
                    # Auto-navigate to Portfolio Signals page if signals found
                    if stock_count > 0:
                        st.info("💡 Click 'Portfolio Signals' to view details")
                    
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {e}")
                    logger.error(f"Signal generation error: {e}", exc_info=True)
        
        st.divider()
        
        # Capital Display
        capital = st.session_state.portfolio_mgr.TOTAL_CAPITAL
        st.metric("💰 Total Capital", f"€{capital:,}")
        st.caption("Allocation:")
        st.caption(f"  • {int(st.session_state.portfolio_mgr.STOCK_ALLOCATION*100)}% Stocks")
        st.caption(f"  • {int(st.session_state.portfolio_mgr.CASH_RESERVE*100)}% Cash")
        
        st.divider()
        
        # Navigation
        st.header("📊 Navigation")
        
        # Handle navigation from quick action buttons
        pages = ["🏠 Home", "🎯 Portfolio Signals", "💼 My Positions", "⚠️ Risk Monitor", "📊 Trade History", "⚙️ Settings"]
        default_index = 0
        
        if 'navigate_to' in st.session_state and st.session_state.navigate_to:
            try:
                default_index = pages.index(st.session_state.navigate_to)
                # Clear the navigation flag
                st.session_state.navigate_to = None
            except ValueError:
                default_index = 0
        
        page = st.radio(
            "Select Page",
            pages,
            index=default_index
        )
    
    # Main content based on selected page
    if page == "🏠 Home":
        render_home_page()
    elif page == "🎯 Portfolio Signals":
        render_portfolio_signals_page()
    elif page == "💼 My Positions":
        render_positions_page()
    elif page == "⚠️ Risk Monitor":
        render_risk_monitor_page()
    elif page == "📊 Trade History":
        render_trade_history_page()
    elif page == "⚙️ Settings":
        render_settings_page()


def render_home_page():
    """Render home page with overview"""
    st.header("🏠 Welcome to Your Trading System")
    
    # Market Status Widget (QoL 1.2)
    market_status = get_market_status()
    status_icon = {
        'open': '🟢',
        'pre-market': '🟡', 
        'after-hours': '🟡',
        'closed': '🔴'
    }.get(market_status['status'], '⚪')
    
    status_text = {
        'open': f"Mercato **APERTO** — Regular Session",
        'pre-market': f"**Pre-Market** — Apertura tra {market_status.get('time_until_open', 'N/A')}",
        'after-hours': f"**After-Hours** — Prossima apertura: {market_status.get('time_until_open', 'N/A')}",
        'closed': f"Mercato **CHIUSO** — {market_status.get('reason', '')}. Prossima apertura: {market_status.get('time_until_open', 'N/A')}"
    }.get(market_status['status'], 'Status sconosciuto')
    
    st.info(f"{status_icon} {status_text}")
    
    # Quick stats
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        capital = st.session_state.portfolio_mgr.TOTAL_CAPITAL
        st.metric("💰 Capital", f"€{capital:,}")
    
    with col2:
        positions = st.session_state.user_db.get_open_trades()
        st.metric("💼 Open Positions", len(positions))
    
    with col3:
        stats = st.session_state.user_db.get_trade_statistics()
        win_rate = stats.get('win_rate', 0)
        st.metric("📈 Win Rate", f"{win_rate:.1f}%")
    
    with col4:
        total_pnl = stats.get('total_pnl', 0)
        st.metric("💵 Total P&L", f"€{total_pnl:.2f}")
    
    st.divider()
    
    # Dynamic Workflow Checklist (QoL 1.3)
    _render_workflow_checklist(market_status, positions)
    
    st.divider()
    
    # Current signals summary
    if st.session_state.signals:
        signals = st.session_state.signals
        
        st.subheader("📊 Current Market Status")
        
        regime = signals.get('regime', {})
        col1, col2, col3 = st.columns(3)
        
        with col1:
            regime_name = regime.get('regime', 'Unknown').upper()
            regime_color = {
                'TRENDING': '🟢',
                'CHOPPY': '🟡',
                'BREAKOUT': '🔵',
                'STRONG_TREND': '🟣'
            }.get(regime_name, '⚪')
            st.metric("Market Regime", f"{regime_color} {regime_name}")
        
        with col2:
            strategy = signals.get('stock_strategy_name', 'Unknown').upper()
            st.metric("Active Strategy", strategy)
        
        with col3:
            total_signals = len(signals.get('stock_signals', []))
            st.metric("Total Signals", total_signals)
        
        st.divider()
        
        # Quick action buttons
        st.subheader("🚀 Quick Actions")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🎯 View Signals", width="stretch"):
                st.session_state.navigate_to = "🎯 Portfolio Signals"
                st.rerun()
        
        with col2:
            if st.button("💼 Manage Positions", width="stretch"):
                st.session_state.navigate_to = "💼 My Positions"
                st.rerun()
        
        with col3:
            if st.button("📊 View History", width="stretch"):
                st.session_state.navigate_to = "📊 Trade History"
                st.rerun()
    
    else:
        st.info("👈 Click **'Generate Signals'** in the sidebar to start analysis")
    
    st.divider()
    
    # System guide
    st.subheader("📖 How to Use This System")
    
    st.markdown("""
    ### Daily Workflow:
    
    1. **📥 Update Data** - Click 'Update Market Data' to get latest prices (morning, before market or after close)
    2. **🔄 Generate Signals** - System analyzes market regime and generates signals
    3. **🎯 Review Signals** - Check Portfolio Signals page for entry recommendations
    4. **💼 Execute on Trade Republic** - Follow the instructions to place orders
    5. **⚠️ Set Stop Loss** - IMMEDIATELY after entry, set stop loss on Trade Republic
    6. **📊 Monitor** - Check 'My Positions' every 3-7 days for trailing stops
    
    ### Key Features:
    
    - **Market Regime Detection**: System identifies market conditions (Trending/Choppy/Breakout/Strong Trend)
    - **Multi-Strategy**: Automatically selects best strategy based on regime
    - **Capital Allocation**: Smart allocation across stocks (90%) and cash (10%)
    - **Risk Management**: Fixed € risk per trade
    - **Autonomous Decisions**: System tells you exactly where to invest and how much
    
    ### Strategies:
    
    - **Momentum** (Trending/Strong Trend): Buy strong uptrends
    - **Mean Reversion** (Choppy): Buy oversold dips in uptrends  
    - **Breakout** (Breakout): Buy consolidation breakouts
    """)


def render_portfolio_signals_page():
    """Render portfolio signals with regime and allocation"""
    st.header("🎯 Portfolio Signals - Your Trading Plan")
    
    if not st.session_state.signals:
        st.warning("⚠️ No signals generated yet. Click 'Generate Signals' in the sidebar.")
        return
    
    signals = st.session_state.signals
    regime = signals.get('regime', {})
    stock_signals = signals.get('stock_signals', [])
    stock_strategy_name = signals.get('stock_strategy_name', 'Unknown')
    
    # Market Regime Section
    st.subheader("📊 Market Regime Analysis")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        regime_name = regime.get('regime', 'Unknown').upper()
        regime_emoji = {
            'TRENDING': '🟢',
            'CHOPPY': '🟡',
            'BREAKOUT': '🔵',
            'STRONG_TREND': '🟣'
        }.get(regime_name, '⚪')
        st.metric("Market Regime", f"{regime_emoji} {regime_name}")
    
    with col2:
        adx = regime.get('adx', 0)
        st.metric("ADX", f"{adx:.1f}")
        st.caption("Trend strength")
    
    with col3:
        trend = regime.get('trend_direction', 'Unknown').upper()
        trend_emoji = "🔼" if trend == "UP" else "🔽" if trend == "DOWN" else "➡️"
        st.metric("Trend Direction", f"{trend_emoji} {trend}")
    
    with col4:
        confidence = regime.get('confidence', 0)
        st.metric("Confidence", f"{confidence:.0f}%")
    
    # Strategy explanation
    st.info(f"""
    **Strategy Selected: {stock_strategy_name.upper()}**
    
    {get_strategy_explanation(stock_strategy_name, regime_name)}
    """)
    
    st.divider()
    
    # Capital Allocation Section
    st.subheader("💰 Capital Allocation")
    
    total_capital = st.session_state.portfolio_mgr.TOTAL_CAPITAL
    stock_capital = total_capital * st.session_state.portfolio_mgr.STOCK_ALLOCATION
    cash_reserve = total_capital * st.session_state.portfolio_mgr.CASH_RESERVE
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Capital", f"€{total_capital:,}")
    
    with col2:
        st.metric("Stock Allocation", f"€{stock_capital:,}")
        st.caption(f"{int(st.session_state.portfolio_mgr.STOCK_ALLOCATION*100)}% - Day/Swing stocks")
    
    with col3:
        st.metric("Cash Reserve", f"€{cash_reserve:,}")
        st.caption(f"{int(st.session_state.portfolio_mgr.CASH_RESERVE*100)}% - Safety buffer")
    
    st.divider()
    
    # Stock Signals Section
    st.subheader(f"📈 Stock Signals ({len(stock_signals)})")
    
    if not stock_signals:
        st.info("No stock signals for current market conditions. Cash is king! 💵")
    else:
        for i, sig in enumerate(stock_signals, 1):
            render_signal_card(sig, i, "STOCK")
    
    st.divider()
    
    # Action Plan Section
    st.subheader("📋 Your Action Plan - Trade Republic")
    
    total_signals = len(stock_signals)
    
    if total_signals == 0:
        st.success("✅ No trades to execute. Hold cash and wait for better opportunities.")
    else:
        st.markdown(f"""
        **You have {total_signals} trade(s) to execute:**
        
        ### Step-by-Step Instructions:
        
        1. **Open Trade Republic app**
        
        2. **For each signal above:**
           - Search for the symbol (e.g., WBD, SPXL)
           - Click 'Buy'
           - Enter the **Quantity** shown above
           - Use **Limit Order** at the Entry Price (or Market if urgent)
           - Confirm purchase
        
        3. **IMMEDIATELY after purchase:**
           - Go to your portfolio in Trade Republic
           - Click on the stock you just bought
           - Set a **Stop Loss** order at the Stop price shown above
           - This protects your capital!
        
        4. **Set Price Alert for Target:**
           - In Trade Republic, set a price alert at the Target price
           - You'll be notified when target is reached
           - Then manually sell the position
        
        5. **Monitor every 3-7 days:**
           - Come back to this dashboard
           - Check 'My Positions' page
           - Update trailing stops if suggested
        
        ### ⚠️ Important Reminders:
        
        - **Stop Loss is MANDATORY** - Set it immediately after entry
        - **Don't skip signals** - Execute all signals or none (portfolio balance)
        - **Use Limit Orders** - Avoid slippage on entry
        - **Commission**: €1 per trade on Trade Republic (already factored in)
        - **Hold period**: 5-15 working days typically
        """)
        
        # Register trades in dashboard
        st.divider()
        st.subheader("📝 After Execution - Register Trades")
        st.info("After you execute trades on Trade Republic, register them here to track performance:")
        
        if st.button("➕ Register My Trades", width="stretch"):
            st.session_state.register_mode = True
            st.rerun()
        
        # Handle register mode - show form
        if st.session_state.get('register_mode', False):
            st.divider()
            st.subheader("📝 Register Executed Trade")
            
            with st.form("register_trade_form"):
                # Pre-fill with signals if available
                signal_symbols = [sig['symbol'] for sig in stock_signals]
                
                col1, col2 = st.columns(2)
                
                with col1:
                    if signal_symbols:
                        symbol = st.selectbox("Symbol", options=signal_symbols, help="Select from generated signals")
                    else:
                        symbol = st.text_input("Symbol", help="Enter stock symbol (e.g., AAPL)")
                    
                    entry_price = st.number_input("Entry Price ($)", min_value=0.01, step=0.01, help="Actual price you paid")
                    quantity = st.number_input("Quantity", min_value=1, step=1, help="Number of shares bought")
                
                with col2:
                    # Auto-fill stop/target from signal if available
                    selected_signal = next((s for s in stock_signals if s['symbol'] == symbol), None) if signal_symbols else None
                    default_stop = selected_signal.get('stop_loss', 0.0) if selected_signal else 0.0
                    default_target = selected_signal.get('target_price', 0.0) if selected_signal else 0.0
                    
                    stop_loss = st.number_input("Stop Loss ($)", min_value=0.01, value=default_stop if default_stop > 0 else 0.01, step=0.01, help="Your stop loss level")
                    target_price = st.number_input("Target Price ($)", min_value=0.01, value=default_target if default_target > 0 else 0.01, step=0.01, help="Your target price")
                
                notes = st.text_area("Notes (optional)", placeholder="Any notes about this trade...")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    submit = st.form_submit_button("✅ Register Trade", type="primary", width="stretch")
                
                with col2:
                    cancel = st.form_submit_button("❌ Cancel", width="stretch")
                
                if submit:
                    if symbol and entry_price > 0 and quantity > 0 and stop_loss > 0:
                        try:
                            st.session_state.user_db.add_trade(
                                symbol=symbol,
                                entry_price=entry_price,
                                quantity=quantity,
                                stop_loss=stop_loss,
                                target_price=target_price if target_price > 0 else None,
                                notes=notes if notes else None
                            )
                            st.success(f"✅ Trade registered: {quantity} shares of {symbol} @ ${entry_price:.2f}")
                            st.session_state.register_mode = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error registering trade: {e}")
                    else:
                        st.warning("⚠️ Please fill in all required fields (Symbol, Entry Price, Quantity, Stop Loss)")
                
                if cancel:
                    st.session_state.register_mode = False
                    st.rerun()


def render_signal_card(sig, index, sig_type="STOCK"):
    """Render a signal card with all details and score-based coloring"""
    symbol = sig['symbol']
    strategy_code = sig.get('strategy', 'unknown')
    entry = sig['entry_price']
    target = sig.get('target_price', entry * 1.05)  # Default 5% target if not set
    stop = sig.get('stop_loss', entry * 0.95)  # Default 5% stop if not set
    quantity = sig.get('position_size', sig.get('quantity', 0))  # Try both names
    risk = sig.get('risk_amount', sig.get('risk_eur', 0))  # Try both names
    score = sig.get('score', 0)
    
    # Simple strategies (momentum_simple, mean_reversion_rsi, breakout) don't use 0-100 scoring
    # They use pass/fail logic - if we have a signal, it passed all filters
    simple_strategies = ['momentum_simple', 'mean_reversion_rsi', 'breakout',
                         'simple_momentum_v2.1', 'mean_reversion', 'momentum']
    is_simple_strategy = strategy_code in simple_strategies
    
    # Strategy name mapping (human-readable)
    strategy_names = {
        'momentum_simple': 'Momentum (Trend Following)',
        'simple_momentum_v2.1': 'Momentum (Trend Following)',
        'momentum': 'Momentum (Trend Following)',
        'mean_reversion_rsi': 'Mean Reversion (Oversold Bounce)',
        'mean_reversion': 'Mean Reversion (Oversold Bounce)',
        'breakout': 'Breakout (Consolidation Break)'
    }
    strategy_display = strategy_names.get(strategy_code, strategy_code)
    
    # Calculate percentages (safely handle None values)
    target_pct = ((target - entry) / entry) * 100 if entry and target else 0
    stop_pct = ((entry - stop) / entry) * 100 if entry and stop else 0
    
    # Color coding based on strategy type
    if is_simple_strategy and score == 0:
        # Simple strategies that passed all filters - show as VALID
        bg_color = "rgba(76, 175, 80, 0.15)"  # Transparent green
        border_color = "#4caf50"  # Solid green
        score_badge = "✅ VALID"
        score_display = ""  # Don't show score for simple strategies
    elif score >= 80:
        bg_color = "rgba(76, 175, 80, 0.15)"  # Transparent green
        border_color = "#4caf50"  # Solid green
        score_badge = "🟢 STRONG"
        score_display = f" ({score}/100)"
    elif score >= 65:
        bg_color = "rgba(33, 150, 243, 0.15)"  # Transparent blue
        border_color = "#2196f3"  # Solid blue
        score_badge = "🔵 MODERATE"
        score_display = f" ({score}/100)"
    elif score >= 50:
        bg_color = "rgba(158, 158, 158, 0.15)"  # Transparent gray
        border_color = "#9e9e9e"  # Solid gray
        score_badge = "⚪ WEAK"
        score_display = f" ({score}/100)"
    else:
        bg_color = "rgba(244, 67, 54, 0.15)"  # Transparent red
        border_color = "#f44336"  # Solid red
        score_badge = "🔴 NO SIGNAL"
        score_display = f" ({score}/100)"
    
    with st.container():
        st.markdown(f"""
        <div style="background-color: {bg_color}; padding: 15px; border-radius: 10px; border-left: 5px solid {border_color};">
            <h3 style="margin: 0;">{index}. {symbol} {'📈' if sig_type == 'STOCK' else '🚀'} <span style="font-size: 0.7em;">{score_badge}{score_display}</span></h3>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric("Entry Price", _fmt_usd(entry))
            st.caption(f"Strategy: {strategy_display}")
        
        with col2:
            st.metric("Target", _fmt_usd(target))
            st.caption(f"+{target_pct:.1f}% profit")
        
        with col3:
            st.metric("Stop Loss", _fmt_usd(stop))
            st.caption(f"-{stop_pct:.1f}% risk")
        
        with col4:
            st.metric("Quantity", f"{quantity} shares")
            total_value = entry * quantity
            st.caption(f"Value: {_fmt_usd(total_value)}")
        
        with col5:
            st.metric("Max Risk", _fmt_eur(risk))
            st.caption("Per position")
        
        st.markdown("---")


def get_strategy_explanation(strategy_name, regime):
    """Get explanation for selected strategy"""
    explanations = {
        "momentum_simple": {
            "TRENDING": "Strong uptrend confirmed. Buying assets above SMA200 with high liquidity.",
            "STRONG_TREND": "Very strong trend. Aggressive momentum for maximum gains.",
            "default": "Momentum strategy: Buying winning stocks in confirmed uptrends."
        },
        "mean_reversion_rsi": {
            "CHOPPY": "Choppy market. Buying oversold dips (RSI<35) in overall uptrends for bounce.",
            "default": "Mean reversion: Buying temporary dips in strong stocks (oversold RSI)."
        },
        "breakout": {
            "BREAKOUT": "Breakout regime detected. Buying consolidation breakouts with volume confirmation.",
            "default": "Breakout strategy: Buying price breakouts from tight ranges."
        }
    }
    
    strategy_expl = explanations.get(strategy_name.lower(), {})
    return strategy_expl.get(regime, strategy_expl.get("default", "Active strategy based on current market conditions."))


def render_positions_page():
    """Render positions management page"""
    st.header("💼 My Open Positions")
    
    positions = st.session_state.user_db.get_open_trades()
    
    if not positions:
        st.info("No open positions. Execute signals from Portfolio Signals page.")
        return
    
    # Handle Manage Position modal/form (unified)
    manage_symbol = st.session_state.get('manage_position_symbol')
    if manage_symbol:
        _render_manage_position_form(manage_symbol, positions)
        return  # Show only the form
    
    # Aggregate stats
    total_invested = 0
    total_unrealized_pnl = 0
    
    for pos in positions:
        try:
            symbol_data = st.session_state.market_db.get_data(pos['symbol'])
            if not symbol_data.empty:
                current_price = symbol_data['close'].iloc[-1]
                pnl = (current_price - pos['entry_price']) * pos['quantity']
                invested = pos['entry_price'] * pos['quantity']
                total_unrealized_pnl += pnl
                total_invested += invested
        except Exception:
            pass
    
    # Display aggregate stats
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Open Positions", len(positions))
    
    with col2:
        st.metric("Total Invested", _fmt_usd(total_invested))
    
    with col3:
        pnl_pct = (total_unrealized_pnl / total_invested * 100) if total_invested > 0 else 0
        st.metric("Unrealized P&L", _fmt_usd(total_unrealized_pnl), delta=f"{pnl_pct:.2f}%")
    
    with col4:
        avg_pnl = total_unrealized_pnl / len(positions) if positions else 0
        st.metric("Avg P&L", _fmt_usd(avg_pnl))
    
    st.divider()
    
    # Display each position
    for pos in positions:
        render_position_card(pos)


def _render_manage_position_form(symbol: str, positions: list):
    """Render unified form for managing a position (update stop or close)"""
    pos = next((p for p in positions if p['symbol'] == symbol), None)
    if not pos:
        st.error(f"Position not found: {symbol}")
        if st.button("⬅️ Back to Positions"):
            st.session_state.manage_position_symbol = None
            st.rerun()
        return
    
    st.subheader(f"📝 Manage Position - {symbol}")
    
    # Get current price
    try:
        symbol_data = st.session_state.market_db.get_data(symbol)
        current_price = symbol_data['close'].iloc[-1] if not symbol_data.empty else pos['entry_price']
    except Exception:
        current_price = pos['entry_price']
    
    current_stop = pos.get('current_stop_loss') or pos.get('stop_loss')
    pnl = (current_price - pos['entry_price']) * pos['quantity']
    pnl_pct = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
    
    # Show current position info
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Entry Price", _fmt_usd(pos['entry_price']))
    
    with col2:
        st.metric("Current Price", _fmt_usd(current_price), delta=f"{pnl_pct:.2f}%")
    
    with col3:
        st.metric("Current Stop", _fmt_usd(current_stop))
    
    with col4:
        st.metric("Unrealized P&L", _fmt_usd(pnl))
    
    st.caption(f"Quantity: {pos['quantity']} shares | Target: {_fmt_usd(pos.get('target_price'))}")
    
    st.divider()
    
    # Check for quick-close pre-fill (QoL 2.3)
    quick_close_price = st.session_state.get('quick_close_price')
    quick_close_reason = st.session_state.get('quick_close_reason')
    
    # Auto-select Close Position if coming from quick-close button
    default_action_index = 1 if quick_close_price else 0
    
    # Action selection
    action = st.radio(
        "What would you like to do?",
        options=["🔄 Update Stop Loss", "✅ Close Position"],
        horizontal=True,
        index=default_action_index
    )
    
    st.divider()
    
    if action == "🔄 Update Stop Loss":
        with st.form("update_stop_form"):
            new_stop = st.number_input(
                "New Stop Loss ($)",
                min_value=0.01,
                value=float(current_stop) if current_stop else float(pos['entry_price'] * 0.95),
                step=0.01,
                help="Enter the new stop loss price"
            )
            
            reason = st.selectbox(
                "Reason",
                options=[
                    "Trailing stop adjustment",
                    "Risk reduction",
                    "Moving to breakeven",
                    "Manual adjustment"
                ]
            )
            
            # Show impact
            if new_stop > 0:
                risk_per_share = pos['entry_price'] - new_stop
                total_risk = risk_per_share * pos['quantity']
                if new_stop >= pos['entry_price']:
                    st.success(f"✅ Breakeven or better! Risk: ${total_risk:.2f}")
                else:
                    st.info(f"Risk per share: ${risk_per_share:.2f} | Total risk: ${total_risk:.2f}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                submit = st.form_submit_button("✅ Update Stop", type="primary", width="stretch")
            
            with col2:
                cancel = st.form_submit_button("⬅️ Back", width="stretch")
            
            if submit:
                if new_stop > 0:
                    try:
                        st.session_state.user_db.update_position_stop(
                            symbol=symbol,
                            new_stop=new_stop,
                            reason=reason
                        )
                        st.success(f"✅ Stop loss updated to ${new_stop:.2f}")
                        st.session_state.manage_position_symbol = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error: {e}")
                else:
                    st.warning("⚠️ Enter a valid stop loss price")
            
            if cancel:
                st.session_state.manage_position_symbol = None
                st.rerun()
    
    else:  # Close Position
        # Determine default values based on quick-close (QoL 2.3)
        default_exit_price = float(quick_close_price) if quick_close_price else float(current_price)
        
        # Map quick_close_reason to selectbox option
        reason_map = {
            "Stop loss hit": "stopped",
            "Target reached": "target_reached"
        }
        default_reason = reason_map.get(quick_close_reason, "manual_close")
        reason_options = ["target_reached", "stopped", "manual_close", "strategy_change"]
        default_reason_index = reason_options.index(default_reason) if default_reason in reason_options else 2
        
        with st.form("close_position_form"):
            exit_price = st.number_input(
                "Exit Price ($)",
                min_value=0.01,
                value=default_exit_price,
                step=0.01,
                help="Actual price you sold at"
            )
            
            reason = st.selectbox(
                "Close Reason",
                options=reason_options,
                index=default_reason_index,
                format_func=lambda x: {
                    "target_reached": "🎯 Target Reached",
                    "stopped": "🛑 Stop Loss Hit",
                    "manual_close": "📝 Manual Close",
                    "strategy_change": "🔄 Strategy Change"
                }.get(x, x)
            )
            
            # Calculate final P&L
            final_pnl = (exit_price - pos['entry_price']) * pos['quantity']
            final_pnl_pct = ((exit_price - pos['entry_price']) / pos['entry_price']) * 100
            
            # Trade Recap Box (QoL 2.2)
            st.markdown("---")
            st.markdown("**📊 Riepilogo Trade**")
            
            # Calculate trade duration
            entry_date = pos.get('entry_date') or pos.get('created_at')
            if entry_date:
                try:
                    if isinstance(entry_date, str):
                        entry_dt = pd.to_datetime(entry_date)
                    else:
                        entry_dt = entry_date
                    trade_duration = (datetime.now() - entry_dt).days
                except Exception:
                    trade_duration = "N/A"
            else:
                trade_duration = "N/A"
            
            # Calculate R-Multiple
            initial_risk = pos['entry_price'] - (pos.get('stop_loss') or pos['entry_price'] * 0.95)
            if initial_risk > 0:
                r_multiple = (exit_price - pos['entry_price']) / initial_risk
            else:
                r_multiple = 0
            
            # Target comparison
            target_price = pos.get('target_price')
            if target_price:
                target_r = (target_price - pos['entry_price']) / initial_risk if initial_risk > 0 else 0
                target_comparison = f"(target era {target_r:.1f}R)"
            else:
                target_comparison = ""
            
            # Estimated commission (€1 per trade on Trade Republic)
            commission_eur = 2.0  # 1€ buy + 1€ sell
            
            # Net in EUR (approximate)
            try:
                from dss.utils.currency import get_cached_exchange_rate
                eur_rate = get_cached_exchange_rate()
            except Exception:
                eur_rate = 0.92
            
            net_eur = (final_pnl * eur_rate) - commission_eur
            
            recap_text = f"""
| Campo | Valore |
|-------|--------|
| **Durata** | {trade_duration} giorni |
| **Entry** | {_fmt_usd(pos['entry_price'])} |
| **Exit** | {_fmt_usd(exit_price)} |
| **P&L** | {_fmt_usd(final_pnl)} ({final_pnl_pct:+.1f}%) |
| **R-Multiple** | {r_multiple:+.2f}R {target_comparison} |
| **Commissioni** | ~€{commission_eur:.2f} |
| **Netto EUR** | ~€{net_eur:.2f} |
"""
            st.markdown(recap_text)
            st.markdown("---")
            
            if final_pnl >= 0:
                st.success(f"💰 Final P&L: ${final_pnl:.2f} (+{final_pnl_pct:.2f}%)")
            else:
                st.error(f"📉 Final P&L: ${final_pnl:.2f} ({final_pnl_pct:.2f}%)")
            
            col1, col2 = st.columns(2)
            
            with col1:
                submit = st.form_submit_button("✅ Close Position", type="primary", width="stretch")
            
            with col2:
                cancel = st.form_submit_button("⬅️ Back", width="stretch")
            
            if submit:
                if exit_price > 0:
                    try:
                        st.session_state.user_db.close_position(
                            symbol=symbol,
                            exit_price=exit_price,
                            reason=reason
                        )
                        st.success(f"✅ Position closed: {symbol} @ ${exit_price:.2f}")
                        st.balloons()
                        # Clear quick-close state
                        st.session_state.quick_close_price = None
                        st.session_state.quick_close_reason = None
                        st.session_state.manage_position_symbol = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error: {e}")
                else:
                    st.warning("⚠️ Enter a valid exit price")
            
            if cancel:
                # Clear quick-close state
                st.session_state.quick_close_price = None
                st.session_state.quick_close_reason = None
                st.session_state.manage_position_symbol = None
                st.rerun()


def render_position_card(pos):
    """Render position management card"""
    symbol = pos['symbol']
    
    try:
        symbol_data = st.session_state.market_db.get_data(symbol)
        if not symbol_data.empty:
            current_price = symbol_data['close'].iloc[-1]
        else:
            current_price = pos['entry_price']
    except Exception:
        current_price = pos['entry_price']
    
    pnl = (current_price - pos['entry_price']) * pos['quantity']
    pnl_pct = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
    
    # Color coding
    color = "green" if pnl >= 0 else "red"
    
    with st.expander(f"{'🟢' if pnl >= 0 else '🔴'} {symbol} - {pos['quantity']} shares @ {_fmt_usd(pos['entry_price'])}", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Entry Price", _fmt_usd(pos['entry_price']))
            st.metric("Current Price", _fmt_usd(current_price), delta=f"{pnl_pct:.2f}%")
        
        with col2:
            st.metric("Stop Loss", _fmt_usd(pos.get('stop_loss')))
            current_stop = pos.get('current_stop_loss') or pos.get('stop_loss')
            if current_stop:
                st.metric("Current Stop", _fmt_usd(current_stop))
        
        with col3:
            st.metric("Target", _fmt_usd(pos.get('target_price')))
            if pos.get('target_price'):
                target_dist = ((pos['target_price'] - current_price) / current_price) * 100
                st.metric("To Target", f"{target_dist:.2f}%")
        
        with col4:
            st.metric("Unrealized P&L", _fmt_usd(pnl), delta=f"{pnl_pct:.2f}%")
            st.metric("Quantity", f"{pos['quantity']} shares")
        
        # Trailing Stop Suggestion (QoL 2.1)
        trailing_suggestion = _get_trailing_stop_suggestion(pos, current_price, pnl_pct)
        if trailing_suggestion:
            st.info(trailing_suggestion)
        
        # Quick Actions Row (QoL 2.3)
        btn_col1, btn_col2, btn_col3 = st.columns(3)
        
        with btn_col1:
            if st.button(f"🛑 Stoppato", key=f"quick_stop_{symbol}", help="Chiudi al prezzo di stop loss"):
                st.session_state.manage_position_symbol = symbol
                st.session_state.quick_close_price = pos.get('current_stop_loss') or pos.get('stop_loss')
                st.session_state.quick_close_reason = "Stop loss hit"
                st.rerun()
        
        with btn_col2:
            if st.button(f"🎯 Target", key=f"quick_target_{symbol}", help="Chiudi al prezzo target"):
                st.session_state.manage_position_symbol = symbol
                st.session_state.quick_close_price = pos.get('target_price')
                st.session_state.quick_close_reason = "Target reached"
                st.rerun()
        
        with btn_col3:
            if st.button(f"📝 Gestisci", key=f"manage_{symbol}", help="Aggiorna stop o chiudi manualmente"):
                st.session_state.manage_position_symbol = symbol
                st.session_state.quick_close_price = None
                st.session_state.quick_close_reason = None
                st.rerun()


def render_trade_history_page():
    """Render trade history page"""
    st.header("📊 Trade History & Statistics")
    
    stats = st.session_state.user_db.get_trade_statistics()
    open_positions = st.session_state.user_db.get_open_trades()
    
    # Show stats even if no closed trades (might have open positions)
    if stats['total_trades'] == 0 and len(open_positions) == 0:
        st.info("No trades yet. Trade history will appear here after you register and close positions.")
        return
    
    # Performance stats
    st.subheader("📈 Performance Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Trades", stats['total_trades'])
        st.metric("Win Rate", f"{stats['win_rate']:.1f}%")
    
    with col2:
        st.metric("Winning Trades", stats['winning_trades'])
        st.metric("Losing Trades", stats['losing_trades'])
    
    with col3:
        st.metric("Total P&L", _fmt_usd(stats['total_pnl']))
        st.metric("Avg P&L", _fmt_usd(stats['avg_pnl']))
    
    with col4:
        st.metric("Avg Win", _fmt_usd(stats['avg_win']))
        st.metric("Avg Loss", _fmt_usd(stats['avg_loss']))
    
    st.divider()
    
    # Trade list
    st.subheader("📋 Closed Trades")
    
    closed_trades = st.session_state.user_db.get_closed_trades(limit=50)
    
    if closed_trades:
        trades_data = []
        for trade in closed_trades:
            pnl = (trade.get('exit_price', 0) - trade.get('entry_price', 0)) * trade.get('quantity', 0)
            pnl_pct = ((trade.get('exit_price', 0) - trade.get('entry_price', 0)) / trade.get('entry_price', 1)) * 100
            
            trades_data.append({
                'Symbol': trade.get('symbol'),
                'Entry': _fmt_usd(trade.get('entry_price')),
                'Exit': _fmt_usd(trade.get('exit_price')),
                'Quantity': trade.get('quantity'),
                'P&L': _fmt_usd(pnl),
                'P&L %': f"{pnl_pct:.2f}%",
                'Entry Date': trade.get('entry_date', 'N/A')[:10],
                'Exit Date': trade.get('exit_date', 'N/A')[:10]
            })
        
        df = pd.DataFrame(trades_data)
        st.dataframe(df, width="stretch", hide_index=True)
    else:
        st.info("No closed trades yet.")
    
    # Reset section
    st.divider()
    st.subheader("🗑️ Reset Trade History")
    st.caption("Clear trade data to start fresh (for paper trading or new strategy)")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Clear closed trades only
        if st.button("🧹 Clear Closed Trades", width="stretch", help="Delete only closed trades, keep open positions"):
            if stats['total_trades'] > 0:
                deleted = st.session_state.user_db.delete_all_closed_trades()
                st.success(f"✅ Cleared {deleted} closed trades")
                st.rerun()
            else:
                st.info("No closed trades to clear")
    
    with col2:
        # Full reset - needs confirmation
        if st.button("🔄 Full Reset (All Trades)", type="secondary", width="stretch", help="Delete ALL trades including open positions"):
            st.session_state.confirm_reset = True
            st.rerun()
    
    # Confirmation dialog for full reset
    if st.session_state.get('confirm_reset', False):
        st.warning("⚠️ **This will delete ALL trades (open and closed). This cannot be undone!**")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Yes, Reset Everything", type="primary", width="stretch"):
                deleted = st.session_state.user_db.reset_all_trades()
                st.session_state.confirm_reset = False
                st.success(f"✅ Reset complete! {deleted} trades deleted. Ready for paper trading!")
                st.balloons()
                st.rerun()
        
        with col2:
            if st.button("❌ Cancel", width="stretch"):
                st.session_state.confirm_reset = False
                st.rerun()


def render_risk_monitor_page():
    """Render Risk Monitor panel per specification"""
    st.header("⚠️ Risk Monitor")
    st.markdown("**Monitor exposure, drawdown, and risk limits**")
    
    # Get drawdown protection status
    try:
        protection = RiskManager.get_drawdown_protection()
        status = protection.get_protection_status()
    except Exception as e:
        logger.error(f"Could not get drawdown protection status: {e}")
        status = {
            'is_trading_allowed': True,
            'is_paused': False,
            'is_stopped': False,
            'risk_multiplier': 1.0,
            'max_positions': 5,
            'consecutive_losses': 0,
            'consecutive_wins': 0,
            'monthly_drawdown_percent': 0,
            'reasons': [],
            'recovery_status': {}
        }
    
    # ==================== ALERT BANNER ====================
    if status.get('is_stopped'):
        st.error("""
        🚨 **ALL TRADING STOPPED**
        
        Monthly drawdown exceeded 10%. Full system review required before resuming.
        
        **Action Required:**
        1. Review all recent trades for mistakes
        2. Verify strategy parameters
        3. Consider reducing position sizes
        4. Contact support if needed
        """)
    elif status.get('is_paused'):
        st.warning("""
        ⚠️ **LIVE TRADING PAUSED**
        
        Monthly drawdown exceeded 6%. Paper trading only until profitable.
        
        **Recovery Requirements:**
        - 1 week of profitable paper trading
        - Review and adjust strategy if needed
        """)
    elif status.get('reasons'):
        for reason in status['reasons']:
            st.warning(f"⚠️ {reason}")
    else:
        st.success("✅ All risk limits within normal parameters")
    
    st.divider()
    
    # ==================== KEY METRICS ====================
    st.subheader("📊 Key Risk Metrics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        dd_pct = status.get('monthly_drawdown_percent', 0)
        dd_color = "normal" if dd_pct < 3 else "off" if dd_pct < 6 else "inverse"
        st.metric(
            "Monthly Drawdown", 
            f"{dd_pct:.1f}%",
            delta=f"{-dd_pct:.1f}%" if dd_pct > 0 else None,
            delta_color=dd_color
        )
        st.caption("Limit: 6% pause, 10% stop")
    
    with col2:
        consec_losses = status.get('consecutive_losses', 0)
        loss_color = "🟢" if consec_losses < 3 else "🟡" if consec_losses < 5 else "🔴"
        st.metric("Consecutive Losses", f"{loss_color} {consec_losses}")
        st.caption("3+ = reduced risk, 5+ = 1 position")
    
    with col3:
        consec_wins = status.get('consecutive_wins', 0)
        st.metric("Consecutive Wins", f"🟢 {consec_wins}")
        recovery = status.get('recovery_status', {})
        if recovery.get('needs_wins_for_normal_risk', 0) > 0:
            st.caption(f"Need {recovery['needs_wins_for_normal_risk']} more wins to recover")
    
    with col4:
        risk_mult = status.get('risk_multiplier', 1.0)
        risk_pct = int(risk_mult * 100)
        risk_emoji = "🟢" if risk_mult >= 1.0 else "🟡" if risk_mult >= 0.5 else "🔴"
        st.metric("Risk Level", f"{risk_emoji} {risk_pct}%")
        st.caption("100% = normal, 50% = reduced")
    
    st.divider()
    
    # ==================== EXPOSURE ANALYSIS ====================
    st.subheader("💰 Current Exposure")
    
    positions = st.session_state.user_db.get_open_trades()
    capital = st.session_state.portfolio_mgr.TOTAL_CAPITAL
    
    if positions:
        total_invested = 0
        sector_exposure = {}  # Track by sector (simplified: by symbol for now)
        
        for pos in positions:
            invested = pos['entry_price'] * pos['quantity']
            total_invested += invested
            
            # Track exposure per symbol
            symbol = pos['symbol']
            sector_exposure[symbol] = sector_exposure.get(symbol, 0) + invested
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            exposure_pct = (total_invested / capital * 100) if capital > 0 else 0
            st.metric("Total Exposure", f"{exposure_pct:.1f}%")
            st.caption(f"${total_invested:,.0f} of €{capital:,.0f}")
        
        with col2:
            st.metric("Open Positions", f"{len(positions)}")
            max_pos = status.get('max_positions', 5)
            st.caption(f"Max allowed: {max_pos}")
        
        with col3:
            # Calculate largest single position
            if sector_exposure:
                max_exposure = max(sector_exposure.values())
                max_symbol = max(sector_exposure, key=sector_exposure.get)
                max_pct = (max_exposure / capital * 100) if capital > 0 else 0
                st.metric("Largest Position", f"{max_pct:.1f}%")
                st.caption(f"{max_symbol}: ${max_exposure:,.0f}")
        
        # Position distribution
        st.subheader("📈 Position Distribution")
        
        pos_data = []
        for pos in positions:
            invested = pos['entry_price'] * pos['quantity']
            pct_of_capital = (invested / capital * 100) if capital > 0 else 0
            
            # Get current price if available
            try:
                symbol_data = st.session_state.market_db.get_data(pos['symbol'])
                current_price = symbol_data['close'].iloc[-1] if not symbol_data.empty else pos['entry_price']
                pnl = (current_price - pos['entry_price']) * pos['quantity']
                pnl_pct = ((current_price - pos['entry_price']) / pos['entry_price'] * 100)
            except Exception:
                current_price = pos['entry_price']
                pnl = 0
                pnl_pct = 0
            
            pos_data.append({
                'Symbol': pos['symbol'],
                'Invested': f"${invested:,.0f}",
                '% of Capital': f"{pct_of_capital:.1f}%",
                'P&L': f"${pnl:,.0f}",
                'P&L %': f"{pnl_pct:.1f}%",
                'Stop Loss': f"${pos.get('stop_loss', 0):.2f}" if pos.get('stop_loss') else "N/A"
            })
        
        df = pd.DataFrame(pos_data)
        st.dataframe(df, width="stretch", hide_index=True)
    else:
        st.info("No open positions. Exposure is 0%.")
    
    st.divider()
    
    # ==================== PROTECTION RULES ====================
    st.subheader("🛡️ Protection Rules Status")
    
    rules = [
        {
            'rule': 'Max 2% risk per trade',
            'status': '✅ Active' if status.get('risk_multiplier', 1.0) >= 1.0 else f"⚠️ Reduced to {status.get('risk_multiplier', 1.0)*2:.1f}%",
            'description': 'Position size calculated to limit loss'
        },
        {
            'rule': 'Max 33% single position',
            'status': '✅ Enforced',
            'description': 'No single stock exceeds 1/3 of capital'
        },
        {
            'rule': '3 loss risk reduction',
            'status': '✅ Armed' if status.get('consecutive_losses', 0) < 3 else '⚠️ ACTIVE',
            'description': 'Reduce to 1% risk after 3 consecutive losses'
        },
        {
            'rule': '5 loss position limit',
            'status': '✅ Armed' if status.get('consecutive_losses', 0) < 5 else '🔴 ACTIVE',
            'description': 'Max 1 position after 5 consecutive losses'
        },
        {
            'rule': '6% monthly pause',
            'status': '✅ Armed' if status.get('monthly_drawdown_percent', 0) < 6 else '⚠️ ACTIVE',
            'description': 'Pause live trading at 6% monthly drawdown'
        },
        {
            'rule': '10% monthly stop',
            'status': '✅ Armed' if status.get('monthly_drawdown_percent', 0) < 10 else '🔴 ACTIVE',
            'description': 'Stop all trading at 10% monthly drawdown'
        }
    ]
    
    for rule in rules:
        with st.expander(f"{rule['status']} {rule['rule']}", expanded=False):
            st.markdown(rule['description'])
    
    st.divider()
    
    # ==================== ACTIONS ====================
    st.subheader("🔧 Actions")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔄 Refresh Status", width="stretch"):
            st.rerun()
    
    with col2:
        if st.button("📅 Start New Month", width="stretch"):
            try:
                protection.start_month(capital)
                st.success("New month started! Drawdown tracking reset.")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")


def render_settings_page():
    """Render settings page"""
    st.header("⚙️ Portfolio Settings")
    st.markdown("Configure your capital, allocation, and risk parameters")
    
    # Force reload portfolio manager to ensure we have latest settings
    portfolio_mgr = st.session_state.portfolio_mgr
    portfolio_mgr.reload_settings()  # Force reload from database
    
    # Current settings summary
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("💰 Total Capital", f"€{portfolio_mgr.TOTAL_CAPITAL:,.0f}")
    with col2:
        st.metric("📈 Stock Allocation", f"{portfolio_mgr.STOCK_ALLOCATION*100:.0f}%")
    with col3:
        st.metric("💵 Cash Reserve", f"{portfolio_mgr.CASH_RESERVE*100:.0f}%")
    
    # Show max positions too
    st.caption(f"Max Stock Positions: {portfolio_mgr.MAX_STOCK_POSITIONS}")
    
    st.divider()
    
    # Capital Management
    st.subheader("💰 Capital Management")
    
    with st.form("capital_form"):
        st.markdown("**Total Available Capital**")
        
        new_capital = st.number_input(
            "Total Capital (€)",
            min_value=1000.0,
            max_value=1000000.0,
            value=float(portfolio_mgr.TOTAL_CAPITAL),
            step=1000.0,
            help="Your total trading capital. This will be allocated across strategies."
        )
        
        st.caption(f"Current: €{portfolio_mgr.TOTAL_CAPITAL:,.0f}")
        
        if st.form_submit_button("💾 Update Capital", type="primary"):
            portfolio_mgr.update_settings(total_capital=new_capital)
            reload_portfolio_manager()
            st.success(f"✅ Capital updated to €{new_capital:,.0f}")
            st.info("💡 Regenerate signals to apply new capital allocation")
            st.rerun()
    
    st.divider()
    
    # Allocation Settings
    st.subheader("📊 Capital Allocation")
    st.caption("How to distribute your capital")
    
    # Stock allocation slider (Cash is calculated automatically)
    stock_pct = st.slider(
        "Stock Allocation (%)",
        min_value=50,
        max_value=100,
        value=int(portfolio_mgr.STOCK_ALLOCATION * 100),
        step=5,
        help="Percentage of capital for stock trades. Cash Reserve = 100% - Stock%"
    )
    
    # Cash is automatically calculated
    cash_pct = 100 - stock_pct
    
    # Show euro amounts
    st.markdown("**Allocation Breakdown:**")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Stock", f"€{portfolio_mgr.TOTAL_CAPITAL * stock_pct / 100:,.0f}")
    with col2:
        st.metric("Cash (auto)", f"€{portfolio_mgr.TOTAL_CAPITAL * cash_pct / 100:,.0f}")
    
    st.caption(f"Stock: {stock_pct}% + Cash: {cash_pct}% = 100%")
    
    if st.button("💾 Update Allocation", type="primary"):
        portfolio_mgr.update_settings(
            stock_allocation=stock_pct / 100,
            cash_reserve=cash_pct / 100
        )
        reload_portfolio_manager()
        st.success("✅ Allocation updated successfully!")
        st.info("💡 Regenerate signals to apply new allocation")
        st.rerun()
    
    st.divider()
    
    # Max Positions
    st.subheader("🔢 Position Limits")
    st.caption("Maximum number of concurrent positions")
    
    with st.form("positions_form"):
        max_stock = st.number_input(
            "Max Stock Positions",
            min_value=1,
            max_value=10,
            value=portfolio_mgr.MAX_STOCK_POSITIONS,
            step=1,
            help="Maximum concurrent stock positions"
        )
        stock_capital = portfolio_mgr.TOTAL_CAPITAL * portfolio_mgr.STOCK_ALLOCATION
        st.caption(f"~€{stock_capital / max_stock:,.0f} per position")
        
        if st.form_submit_button("💾 Update Limits", type="primary"):
            portfolio_mgr.update_settings(
                max_stock_positions=max_stock
            )
            reload_portfolio_manager()
            st.success("✅ Position limits updated!")
            st.info("💡 Regenerate signals to apply new limits")
            st.rerun()
    
    st.divider()
    
    # Risk per Trade
    st.subheader("⚠️ Risk per Trade")
    st.caption("Maximum risk (loss) per individual position")
    
    # Load current risk settings
    stock_risk_str = st.session_state.user_db.get_setting("risk_per_stock_trade")
    stock_risk = float(stock_risk_str) if stock_risk_str else 20.0
    
    with st.form("risk_form"):
        # Max risk = 5% of capital (reasonable upper limit)
        max_risk = portfolio_mgr.TOTAL_CAPITAL * 0.05
        new_stock_risk = st.number_input(
            "Risk per Trade (€)",
            min_value=10.0,
            max_value=max_risk,
            value=min(stock_risk, max_risk),
            step=10.0,
            help="Maximum loss per position (if stop loss hit)"
        )
        stock_pct_risk = (new_stock_risk / portfolio_mgr.TOTAL_CAPITAL) * 100
        st.caption(f"{stock_pct_risk:.2f}% of total capital")
        
        st.markdown("**Risk Recommendations:**")
        st.markdown(f"""
        - **Conservative**: 1-1.5% of capital per trade
        - **Moderate**: 2-3% of capital per trade  
        - **Aggressive**: 4-5% of capital per trade
        
        Your setting: {stock_pct_risk:.2f}% (€{new_stock_risk:.0f})
        """)
        
        if st.form_submit_button("💾 Update Risk", type="primary"):
            st.session_state.user_db.set_setting("risk_per_stock_trade", str(new_stock_risk))
            
            # Reload portfolio manager to apply new risk settings
            reload_portfolio_manager()
            
            st.success("✅ Risk per trade updated!")
            st.info("💡 Regenerate signals to apply new risk parameters")
            st.rerun()
    
    st.divider()
    
    # Exchange Rate (auto-updated)
    st.subheader("💱 Exchange Rate (USD → EUR)")
    
    from dss.utils.currency import get_exchange_rate
    current_rate = get_exchange_rate(user_db=st.session_state.user_db)
    
    st.metric("Current Rate", f"1 USD = {current_rate:.4f} EUR")
    st.caption("🔄 Auto-updated from API at app startup")
    
    st.divider()
    
    # Presets
    st.subheader("🎯 Quick Presets")
    st.caption("Apply predefined configurations based on your capital and strategy")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("💼 Conservative", width="stretch"):
            # For smaller capital (€1,000 - €5,000)
            portfolio_mgr.update_settings(
                stock_allocation=0.80,
                cash_reserve=0.20,
                max_stock_positions=3
            )
            st.session_state.user_db.set_setting("risk_per_stock_trade", "15")
            reload_portfolio_manager()
            st.success("""
            ✅ **Conservative Preset Applied!**
            - Allocation: 80% Stock, 20% Cash
            - Max Positions: 3
            - Risk: €15 per trade
            """)
            st.info("💡 Scroll up to see updated metrics")
            st.rerun()
    
    with col2:
        if st.button("⚖️ Balanced", width="stretch"):
            # For medium capital (€5,000 - €15,000)
            portfolio_mgr.update_settings(
                stock_allocation=0.90,
                cash_reserve=0.10,
                max_stock_positions=5
            )
            st.session_state.user_db.set_setting("risk_per_stock_trade", "20")
            reload_portfolio_manager()
            st.success("""
            ✅ **Balanced Preset Applied!**
            - Allocation: 90% Stock, 10% Cash
            - Max Positions: 5
            - Risk: €20 per trade
            """)
            st.info("💡 Scroll up to see updated metrics")
            st.rerun()
    
    with col3:
        if st.button("🎯 Smart/Hybrid (PAC)", width="stretch"):
            # Optimized for PAC (Piano di Accumulo) with monthly deposits
            portfolio_mgr.update_settings(
                stock_allocation=0.90,
                cash_reserve=0.10,
                max_stock_positions=5
            )
            st.session_state.user_db.set_setting("risk_per_stock_trade", "25")
            reload_portfolio_manager()
            st.success("""
            ✅ **Smart/Hybrid Preset Applied!**
            - 🎯 **Optimized for PAC** (monthly deposits €500-€1,000)
            - Allocation: 90% Stock, 10% Cash
            - Max Positions: 5
            - Risk: €25 per trade
            """)
            st.info("💡 Scroll up to see updated metrics")
            st.rerun()
    
    with col4:
        if st.button("🚀 Aggressive", width="stretch"):
            # For larger capital (€20,000+)
            portfolio_mgr.update_settings(
                stock_allocation=0.95,
                cash_reserve=0.05,
                max_stock_positions=6
            )
            st.session_state.user_db.set_setting("risk_per_stock_trade", "30")
            reload_portfolio_manager()
            st.success("""
            ✅ **Aggressive Preset Applied!**
            - Allocation: 95% Stock, 5% Cash
            - Max Positions: 6
            - Risk: €30 per trade
            """)
            st.info("💡 Scroll up to see updated metrics")
            st.rerun()
    
    st.divider()
    
    # Reset to defaults
    st.subheader("🔄 Reset to Defaults")
    st.caption("Restore original system settings (€10,000 capital, balanced allocation)")
    
    if st.button("🔄 Reset All Settings", type="secondary"):
        portfolio_mgr.update_settings(
            total_capital=10000.0,
            stock_allocation=0.90,
            cash_reserve=0.10,
            max_stock_positions=5
        )
        st.session_state.user_db.set_setting("risk_per_stock_trade", "20")
        reload_portfolio_manager()
        st.success("""
        ✅ **Settings Reset to Defaults!**
        - Capital: €10,000
        - Allocation: 90% Stock, 10% Cash
        - Max Positions: 5
        - Risk: €20 per trade
        """)
        st.info("💡 Scroll up to see updated metrics")
        st.rerun()


if __name__ == "__main__":
    main()
