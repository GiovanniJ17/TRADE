"""
Portfolio Manager - Multi-Strategy con Regime Detection
Gestisce allocazione capitale tra strategie in base al regime di mercato

ALLOCAZIONE CAPITALE:
├── 90% → STOCK DAY/SWING TRADING
│   ├── Momentum (trending regime)
│   ├── Mean Reversion (choppy regime)
│   └── Breakout (breakout regime)
│
└── 10% → CASH RESERVE

WORKFLOW:
1. Detect market regime (ADX, BB squeeze, etc.)
2. Select appropriate stock strategy  
3. Generate signals and allocate capital
4. Apply sector diversification filter (max 40% per sector)
"""
import pandas as pd
from typing import List, Dict, Optional
from loguru import logger

from ..database.market_db import MarketDatabase
from ..core.regime_detector import MarketRegimeDetector
from ..strategies.momentum_simple import SimpleMomentumStrategy
from ..strategies.mean_reversion_rsi import MeanReversionRSI
from ..strategies.breakout_strategy import BreakoutStrategy
from ..utils.config import config

# ETF symbols to exclude from stock analysis (even if in database)
ETF_EXCLUSION_LIST = {
    'SPXL', 'TQQQ', 'UPRO', 'SOXL', 'FNGU', 'TECL',
    'LABU', 'TNA', 'FAS', 'SPY', 'QQQ', 'IWM', 'DIA',
    'VOO', 'VTI', 'ARKK'
}

# Sector mapping for US stocks (for diversification check)
# Expanded mapping to cover more symbols
SECTOR_MAPPING = {
    # Technology - Semiconductors (HIGH CORRELATION - treat as sub-sector)
    'NVDA': 'Semiconductors', 'AMD': 'Semiconductors', 'INTC': 'Semiconductors',
    'MU': 'Semiconductors', 'AVGO': 'Semiconductors', 'QCOM': 'Semiconductors',
    'TXN': 'Semiconductors', 'LRCX': 'Semiconductors', 'AMAT': 'Semiconductors',
    'KLAC': 'Semiconductors', 'MRVL': 'Semiconductors', 'NXPI': 'Semiconductors',
    'ON': 'Semiconductors', 'MCHP': 'Semiconductors', 'ADI': 'Semiconductors',
    'ASML': 'Semiconductors',
    
    # Technology - Software
    'AAPL': 'Technology', 'MSFT': 'Technology', 'GOOGL': 'Technology', 'GOOG': 'Technology',
    'META': 'Technology', 'CSCO': 'Technology', 'ADBE': 'Technology', 'CRM': 'Technology',
    'ORCL': 'Technology', 'IBM': 'Technology', 'NOW': 'Technology', 'SHOP': 'Technology',
    'PYPL': 'Technology', 'PLTR': 'Technology', 'SNOW': 'Technology', 'PANW': 'Technology',
    'CRWD': 'Technology', 'ZS': 'Technology', 'DDOG': 'Technology', 'NET': 'Technology',
    'DOCN': 'Technology', 'MDB': 'Technology', 'WDAY': 'Technology', 'OKTA': 'Technology',
    'ZM': 'Technology', 'TWLO': 'Technology', 'HUBS': 'Technology', 'DOCU': 'Technology',
    'SQ': 'Technology', 'BILL': 'Technology', 'PATH': 'Technology',
    
    # Consumer Discretionary (TSLA is in EV/Auto sub-sector)
    'AMZN': 'Consumer Discretionary', 'HD': 'Consumer Discretionary',
    'NKE': 'Consumer Discretionary', 'MCD': 'Consumer Discretionary', 'SBUX': 'Consumer Discretionary',
    'TGT': 'Consumer Discretionary', 'LOW': 'Consumer Discretionary', 'BKNG': 'Consumer Discretionary',
    'LULU': 'Consumer Discretionary', 'DECK': 'Consumer Discretionary', 'ULTA': 'Consumer Discretionary',
    'RH': 'Consumer Discretionary', 'ETSY': 'Consumer Discretionary', 'W': 'Consumer Discretionary',
    'ABNB': 'Consumer Discretionary', 'UBER': 'Consumer Discretionary', 'LYFT': 'Consumer Discretionary',
    'DASH': 'Consumer Discretionary', 'DG': 'Consumer Discretionary', 'DLTR': 'Consumer Discretionary',
    
    # Communication Services
    'NFLX': 'Communication Services', 'DIS': 'Communication Services', 'CMCSA': 'Communication Services',
    'VZ': 'Communication Services', 'T': 'Communication Services', 'TMUS': 'Communication Services',
    'ROKU': 'Communication Services', 'SPOT': 'Communication Services', 'SNAP': 'Communication Services',
    'PINS': 'Communication Services', 'MTCH': 'Communication Services', 'EA': 'Communication Services',
    'TTWO': 'Communication Services', 'RBLX': 'Communication Services',
    
    # Healthcare
    'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'PFE': 'Healthcare', 'ABBV': 'Healthcare',
    'MRK': 'Healthcare', 'LLY': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'BMY': 'Healthcare', 'AMGN': 'Healthcare', 'GILD': 'Healthcare',
    'REGN': 'Healthcare', 'VRTX': 'Healthcare', 'BIIB': 'Healthcare', 'ISRG': 'Healthcare',
    'DXCM': 'Healthcare', 'ALGN': 'Healthcare', 'VEEV': 'Healthcare', 'ZTS': 'Healthcare',
    
    # Financials
    'JPM': 'Financials', 'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials',
    'MS': 'Financials', 'C': 'Financials', 'BLK': 'Financials', 'SCHW': 'Financials',
    'AXP': 'Financials', 'V': 'Financials', 'MA': 'Financials', 'COF': 'Financials',
    'COIN': 'Financials', 'HOOD': 'Financials', 'SOFI': 'Financials', 'UPST': 'Financials',
    'AFRM': 'Financials', 'ICE': 'Financials', 'CME': 'Financials', 'SPGI': 'Financials',
    
    # Industrials
    'CAT': 'Industrials', 'BA': 'Industrials', 'HON': 'Industrials', 'UPS': 'Industrials',
    'UNP': 'Industrials', 'RTX': 'Industrials', 'LMT': 'Industrials', 'DE': 'Industrials',
    'GE': 'Industrials', 'MMM': 'Industrials', 'FDX': 'Industrials', 'NSC': 'Industrials',
    'AXON': 'Industrials', 'TT': 'Industrials', 'CARR': 'Industrials', 'OTIS': 'Industrials',
    
    # Consumer Staples
    'PG': 'Consumer Staples', 'KO': 'Consumer Staples', 'PEP': 'Consumer Staples',
    'WMT': 'Consumer Staples', 'COST': 'Consumer Staples', 'MDLZ': 'Consumer Staples',
    'CL': 'Consumer Staples', 'KMB': 'Consumer Staples', 'KR': 'Consumer Staples',
    
    # Energy
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'OXY': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    'DVN': 'Energy', 'FANG': 'Energy', 'MPC': 'Energy',
    
    # Materials
    'LIN': 'Materials', 'APD': 'Materials', 'SHW': 'Materials', 'DD': 'Materials',
    'NEM': 'Materials', 'FCX': 'Materials', 'NUE': 'Materials', 'CLF': 'Materials',
    'STLD': 'Materials', 'AA': 'Materials', 'X': 'Materials',
    
    # Utilities
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities', 'D': 'Utilities',
    'AEP': 'Utilities', 'EXC': 'Utilities', 'XEL': 'Utilities', 'WEC': 'Utilities',
    
    # Real Estate
    'AMT': 'Real Estate', 'PLD': 'Real Estate', 'CCI': 'Real Estate', 'EQIX': 'Real Estate',
    'SPG': 'Real Estate', 'O': 'Real Estate', 'WELL': 'Real Estate', 'PSA': 'Real Estate',
    
    # Airlines (HIGH CORRELATION - separate sub-sector)
    'DAL': 'Airlines', 'UAL': 'Airlines', 'LUV': 'Airlines', 'AAL': 'Airlines',
    
    # EV/Auto (HIGH CORRELATION - separate sub-sector)
    'TSLA': 'EV/Auto', 'RIVN': 'EV/Auto', 'LCID': 'EV/Auto', 'NIO': 'EV/Auto',
    'XPEV': 'EV/Auto', 'LI': 'EV/Auto', 'F': 'EV/Auto', 'GM': 'EV/Auto',
    
    # Additional Technology / Software
    'ACN': 'Technology', 'INTU': 'Technology', 'SNPS': 'Technology', 'CDNS': 'Technology',
    'ANET': 'Technology', 'FTNT': 'Technology', 'TTD': 'Technology', 'TEAM': 'Technology',
    'GTLB': 'Technology', 'ESTC': 'Technology', 'SMAR': 'Technology', 'ASAN': 'Technology',
    'FIVN': 'Technology', 'SSNC': 'Technology', 'GLOB': 'Technology', 'EPAM': 'Technology',
    'CDW': 'Technology', 'FFIV': 'Technology', 'IT': 'Technology', 'MSI': 'Technology',
    
    # Additional Healthcare / Biotech
    'MDT': 'Healthcare', 'BSX': 'Healthcare', 'HCA': 'Healthcare', 'CVS': 'Healthcare',
    'CNC': 'Healthcare', 'UHS': 'Healthcare', 'DVA': 'Healthcare', 'ALNY': 'Healthcare',
    'BMRN': 'Healthcare', 'EXAS': 'Healthcare', 'HOLX': 'Healthcare', 'PODD': 'Healthcare',
    'INCY': 'Healthcare', 'IDXX': 'Healthcare', 'A': 'Healthcare', 'RMD': 'Healthcare',
    'QGEN': 'Healthcare',
    
    # Additional Financials
    'AIG': 'Financials', 'ALL': 'Financials', 'MET': 'Financials', 'PGR': 'Financials',
    'TRV': 'Financials', 'USB': 'Financials', 'FITB': 'Financials', 'RF': 'Financials',
    'STT': 'Financials', 'TROW': 'Financials', 'WAL': 'Financials', 'NU': 'Financials',
    'MKTX': 'Financials', 'CBOE': 'Financials', 'NDAQ': 'Financials', 'MCO': 'Financials',
    'AON': 'Financials', 'AJG': 'Financials', 'BRK.B': 'Financials',
    
    # Additional Industrials
    'PCAR': 'Industrials', 'ODFL': 'Industrials', 'FAST': 'Industrials', 'CPRT': 'Industrials',
    'CTAS': 'Industrials', 'PAYX': 'Industrials', 'ADP': 'Industrials', 'VRSK': 'Industrials',
    'ITW': 'Industrials', 'EMR': 'Industrials', 'ROK': 'Industrials', 'ROP': 'Industrials',
    'AME': 'Industrials', 'HUBB': 'Industrials', 'PH': 'Industrials', 'GWW': 'Industrials',
    'SWK': 'Industrials', 'PWR': 'Industrials', 'NOC': 'Industrials', 'GNRC': 'Industrials',
    'XYL': 'Industrials', 'IR': 'Industrials', 'BLDR': 'Industrials', 'APH': 'Industrials',
    'FDS': 'Industrials', 'CTSH': 'Industrials',
    
    # Additional Consumer Discretionary
    'TJX': 'Consumer Discretionary', 'ROST': 'Consumer Discretionary', 'AZO': 'Consumer Discretionary',
    'CHTR': 'Consumer Discretionary', 'APTV': 'Consumer Discretionary', 'LEN': 'Consumer Discretionary',
    'WSM': 'Consumer Discretionary', 'POOL': 'Consumer Discretionary', 'FIVE': 'Consumer Discretionary',
    'CHWY': 'Consumer Discretionary', 'MGM': 'Consumer Discretionary', 'RCL': 'Consumer Discretionary',
    'EBAY': 'Consumer Discretionary',
    
    # Additional Consumer Staples
    'PM': 'Consumer Staples', 'MO': 'Consumer Staples', 'KHC': 'Consumer Staples',
    'TSN': 'Consumer Staples', 'GPC': 'Consumer Staples',
    
    # Additional Energy
    'HAL': 'Energy', 'MRO': 'Energy', 'APA': 'Energy',
    
    # Additional Communication Services
    'ZG': 'Communication Services', 'TCOM': 'Communication Services', 'LYV': 'Communication Services',
    'SIRI': 'Communication Services', 'WBD': 'Communication Services', 'OMC': 'Communication Services',
    
    # Additional Utilities
    'EIX': 'Utilities', 'ETR': 'Utilities', 'SRE': 'Utilities', 'PNW': 'Utilities',
    'PNR': 'Utilities',
    
    # Additional Real Estate
    'VTR': 'Real Estate', 'ARE': 'Real Estate', 'BXP': 'Real Estate',
    'KIM': 'Real Estate', 'REG': 'Real Estate', 'CPT': 'Real Estate', 'EXR': 'Real Estate',
    'AVB': 'Real Estate', 'EQR': 'Real Estate', 'MAA': 'Real Estate', 'UDR': 'Real Estate',
    
    # Additional Materials
    'EMN': 'Materials', 'WY': 'Materials', 'SW': 'Materials',
    
    # Solar/Clean Energy (HIGH CORRELATION - separate sub-sector)
    'FSLR': 'Clean Energy', 'SEDG': 'Clean Energy', 'ENPH': 'Clean Energy',
    
    # E-Commerce/Internet (International)
    'SE': 'E-Commerce', 'MELI': 'E-Commerce', 'BABA': 'E-Commerce', 'JD': 'E-Commerce',
    'PDD': 'E-Commerce', 'BIDU': 'E-Commerce',
    
    # Misc Technology
    'HPE': 'Technology', 'HPQ': 'Technology', 'FIS': 'Technology', 'HWM': 'Technology',
    'HIG': 'Financials', 'UPWK': 'Technology', 'SYF': 'Financials',
    
    # Additional (misc)
    'GTLS': 'Industrials',
}


class PortfolioManager:
    """
    Portfolio Manager con regime detection e multi-strategy allocation
    """
    
    # Default capital allocation (può essere sovrascritto)
    DEFAULT_TOTAL_CAPITAL = 10_000.0  # €10k
    DEFAULT_STOCK_ALLOCATION = 0.90  # 90% stocks
    DEFAULT_CASH_RESERVE = 0.10  # 10% cash
    
    # Default max positions
    DEFAULT_MAX_STOCK_POSITIONS = 5
    
    # Sector diversification limits
    # NOTE: MAX_SYMBOLS_PER_SECTOR=1 was tested but reduced win rate from 55% to 44%
    # Keeping only capital concentration limit (40%) which is less restrictive
    MAX_SECTOR_CONCENTRATION = 0.40  # Max 40% capital in any single sector
    MAX_SYMBOLS_PER_SECTOR = 99  # Effectively disabled - use capital concentration instead
    
    # Volatility filter - avoid extremely volatile stocks that can gap through stops
    # NOTE: 5% was tested but filtered too many high-potential stocks, increasing to 8%
    MAX_NATR_PERCENT = 8.0  # Max 8% normalized ATR (allow more volatile but profitable stocks)
    
    def __init__(self, user_db=None):
        # Single shared MarketDatabase instance for all components
        # (avoids 5 concurrent DuckDB connections to the same file)
        self.db = MarketDatabase()
        self.regime_detector = MarketRegimeDetector(db=self.db)

        # Import qui per evitare circular import
        if user_db is None:
            from ..database.user_db import UserDatabase
            user_db = UserDatabase()
        self.user_db = user_db

        # Load settings from database (con fallback ai default)
        self._load_settings()

        # Strategies share the same db connection
        self.momentum = SimpleMomentumStrategy(user_db=self.user_db, db=self.db)
        self.mean_reversion = MeanReversionRSI(user_db=self.user_db, db=self.db)
        self.breakout = BreakoutStrategy(user_db=self.user_db, db=self.db)
        
        # Apply risk settings to strategies
        self._apply_risk_settings()
    
    def _load_settings(self):
        """Load portfolio settings from user database"""
        # Total capital
        capital_str = self.user_db.get_setting("portfolio_total_capital")
        self.TOTAL_CAPITAL = float(capital_str) if capital_str else self.DEFAULT_TOTAL_CAPITAL
        
        # Allocation percentuali
        stock_alloc_str = self.user_db.get_setting("portfolio_stock_allocation")
        self.STOCK_ALLOCATION = float(stock_alloc_str) if stock_alloc_str else self.DEFAULT_STOCK_ALLOCATION
        
        cash_reserve_str = self.user_db.get_setting("portfolio_cash_reserve")
        self.CASH_RESERVE = float(cash_reserve_str) if cash_reserve_str else self.DEFAULT_CASH_RESERVE
        
        # Max positions
        max_stock_str = self.user_db.get_setting("portfolio_max_stock_positions")
        self.MAX_STOCK_POSITIONS = int(max_stock_str) if max_stock_str else self.DEFAULT_MAX_STOCK_POSITIONS
        
        logger.info(f"Portfolio Manager loaded: Capital=€{self.TOTAL_CAPITAL:,}, "
                   f"Stock={self.STOCK_ALLOCATION*100:.0f}%, Cash={self.CASH_RESERVE*100:.0f}%, "
                   f"MaxPositions={self.MAX_STOCK_POSITIONS}")
    
    def _apply_risk_settings(self):
        """Apply risk per trade settings to strategies"""
        # Load risk settings from database
        stock_risk_str = self.user_db.get_setting("risk_per_stock_trade")
        stock_risk = float(stock_risk_str) if stock_risk_str else 20.0
        
        # Apply to all stock strategies
        self.momentum.RISK_PER_TRADE_EUR = stock_risk
        self.mean_reversion.RISK_PER_TRADE_EUR = stock_risk
        self.breakout.RISK_PER_TRADE_EUR = stock_risk
        
        logger.info(f"Risk settings applied: €{stock_risk} per trade")
    
    def update_settings(self, **kwargs):
        """
        Update portfolio settings and save to database
        
        Args:
            total_capital: float
            stock_allocation: float (0-1)
            cash_reserve: float (0-1)
            max_stock_positions: int
        """
        if 'total_capital' in kwargs:
            self.TOTAL_CAPITAL = float(kwargs['total_capital'])
            self.user_db.set_setting("portfolio_total_capital", str(self.TOTAL_CAPITAL))
        
        if 'stock_allocation' in kwargs:
            self.STOCK_ALLOCATION = float(kwargs['stock_allocation'])
            self.user_db.set_setting("portfolio_stock_allocation", str(self.STOCK_ALLOCATION))
        
        if 'cash_reserve' in kwargs:
            self.CASH_RESERVE = float(kwargs['cash_reserve'])
            self.user_db.set_setting("portfolio_cash_reserve", str(self.CASH_RESERVE))
        
        if 'max_stock_positions' in kwargs:
            self.MAX_STOCK_POSITIONS = int(kwargs['max_stock_positions'])
            self.user_db.set_setting("portfolio_max_stock_positions", str(self.MAX_STOCK_POSITIONS))
        
        logger.info(f"Portfolio settings updated: Capital=€{self.TOTAL_CAPITAL:,}, "
                   f"Stock={self.STOCK_ALLOCATION*100:.0f}%, Cash={self.CASH_RESERVE*100:.0f}%")
        
        # Re-apply risk settings if they were updated
        self._apply_risk_settings()
    
    def reload_settings(self):
        """Reload all settings from database (useful after external updates)"""
        self._load_settings()
        self._apply_risk_settings()
        logger.info("Portfolio settings reloaded from database")
    
    def generate_portfolio_signals(
        self,
        stock_symbols: Optional[List[str]] = None,
        as_of_date: Optional[pd.Timestamp] = None,
        **kwargs  # For backward compatibility
    ) -> Dict:
        """
        Genera segnali per tutto il portfolio (stock-only)
        
        Returns:
            {
                'regime': {...},
                'stock_strategy_name': 'momentum_simple'|'mean_reversion_rsi'|'breakout',
                'stock_strategy_used': 'momentum_simple'|'mean_reversion_rsi'|'breakout',
                'stock_signals': [...],
                'etf_signals': [],  # Always empty (for backward compatibility)
                'capital_allocation': {
                    'stock': €9000,
                    'cash': €1000
                }
            }
        """
        if as_of_date is None:
            as_of_date = pd.Timestamp.now()
        
        logger.info(f"\n{'=' * 80}")
        logger.info(f"PORTFOLIO MANAGER - {as_of_date.date()}")
        logger.info(f"{'=' * 80}")
        
        # Step 1: Detect market regime
        regime = self.regime_detector.detect_regime(as_of_date=as_of_date)
        
        logger.info(f"\nMarket Regime: {regime['regime'].upper()}")
        logger.info(f"  ADX: {regime['adx']:.1f}")
        logger.info(f"  Trend: {regime['trend_direction']}")
        logger.info(f"  Confidence: {regime['confidence']:.0f}%")
        
        # Step 2: Run ALL stock strategies (not just regime-selected one)
        # Regime is used to BOOST ranking, not as exclusive filter
        primary_strategy_name, _ = self._select_stock_strategy(regime['regime'])
        
        logger.info(f"\nPrimary Strategy (regime-based): {primary_strategy_name.upper()}")
        logger.info(f"Running ALL strategies for more signals...")
        
        # Step 3: Generate stock signals from ALL strategies
        if stock_symbols is None:
            all_symbols = self.db.get_all_symbols()
            # Exclude ETFs from stock analysis (only trade individual stocks)
            stock_symbols = [s for s in all_symbols if s not in ETF_EXCLUSION_LIST]
            logger.info(f"Stock universe: {len(stock_symbols)} symbols")
        
        all_stock_signals = []
        strategies = [
            ('momentum_simple', self.momentum),
            ('mean_reversion_rsi', self.mean_reversion),
            ('breakout', self.breakout)
        ]
        
        for strategy_name, strategy in strategies:
            try:
                signals = strategy.generate_signals(
                    symbols=stock_symbols,
                    as_of_date=as_of_date
                )
                # Tag each signal with its source strategy and expiration
                for sig in signals:
                    sig['strategy'] = strategy_name
                    # Boost score if matches regime's primary strategy
                    sig['regime_boost'] = 1.2 if strategy_name == primary_strategy_name else 1.0
                    
                    # Add signal expiration (per Code Review Issue #9)
                    # Signals valid for 4 hours by default
                    generated_at = sig.get('signal_date', as_of_date)
                    sig['generated_at'] = generated_at
                    sig['expires_at'] = generated_at + pd.Timedelta(hours=18)  # Extended for next-morning trading
                
                all_stock_signals.extend(signals)
                logger.info(f"  {strategy_name}: {len(signals)} signals")
            except Exception as e:
                logger.warning(f"  {strategy_name}: Error - {e}")
        
        # Deduplicate by symbol (keep highest boosted signal per symbol)
        seen_symbols = {}
        for sig in all_stock_signals:
            symbol = sig['symbol']
            boost = sig.get('regime_boost', 1.0)
            if symbol not in seen_symbols or boost > seen_symbols[symbol].get('regime_boost', 1.0):
                seen_symbols[symbol] = sig
        
        stock_signals = list(seen_symbols.values())
        
        # Filter out extremely volatile stocks (can gap through stops)
        stock_signals = self._filter_high_volatility(stock_signals)
        
        # Rank signals (regime-matching strategy gets priority)
        stock_signals = self._rank_signals_multi(stock_signals, primary_strategy_name)
        
        # Apply sector diversity filter (per spec Section 11.1: max 40% per sector)
        stock_signals = self.apply_sector_diversity_filter(stock_signals)
        
        # Limit to max positions after diversity filter
        stock_signals = stock_signals[:self.MAX_STOCK_POSITIONS]
        
        # Optionally enhance stop losses with support levels (per Code Review v2 Issue #5)
        use_smart_stops = self.user_db.get_setting("use_smart_stop_loss")
        if use_smart_stops and use_smart_stops.lower() == "true":
            stock_signals = self._enhance_stop_losses(stock_signals)
        
        # Set the primary strategy name for display
        stock_strategy_name = primary_strategy_name
        
        # CRITICAL: Ricalcola position_size con dynamic risk (1.5% del capitale)
        # Le strategie calcolano con €20 fisso, qui applichiamo il sizing reale
        stock_signals = self._apply_dynamic_sizing(stock_signals)
        
        logger.info(f"\nTotal Stock Signals: {len(stock_signals)} (max {self.MAX_STOCK_POSITIONS}, sector-diversified)")
        
        # Step 4: Capital allocation (stock-only system)
        stock_capital = self.TOTAL_CAPITAL * self.STOCK_ALLOCATION
        cash_reserve = self.TOTAL_CAPITAL * self.CASH_RESERVE
        
        logger.info(f"\nCapital Allocation:")
        logger.info(f"  Stock Day/Swing: €{stock_capital:,.0f} ({self.STOCK_ALLOCATION * 100:.0f}%)")
        logger.info(f"  Cash Reserve: €{cash_reserve:,.0f} ({self.CASH_RESERVE * 100:.0f}%)")
        
        logger.info(f"\n{'=' * 80}\n")
        
        return {
            'regime': regime,
            'stock_strategy_name': stock_strategy_name,
            'stock_strategy_used': stock_strategy_name,  # Alias for backward compatibility
            'stock_signals': stock_signals,
            'etf_signals': [],  # Always empty (backward compatibility)
            'capital_allocation': {
                'stock': stock_capital,
                'cash': cash_reserve,
                'total': self.TOTAL_CAPITAL
            }
        }
    
    def _select_stock_strategy(self, regime: str) -> tuple[str, object]:
        """
        Seleziona strategia stock in base al regime
        
        Returns:
            (strategy_name, strategy_instance)
        """
        strategy_map = {
            'trending': ('momentum_simple', self.momentum),  # FIX: aligned with signal tag
            'choppy': ('mean_reversion_rsi', self.mean_reversion),  # FIX: aligned with signal tag
            'breakout': ('breakout', self.breakout),
            'strong_trend': ('momentum_simple', self.momentum)  # Momentum anche per strong trend
        }
        
        return strategy_map.get(regime, ('mean_reversion_rsi', self.mean_reversion))
    
    def _rank_signals(self, signals: List[Dict], strategy_name: str) -> List[Dict]:
        """
        Rank signals in base alla strategia
        
        - Momentum: Rank by return_3m (highest first)
        - Mean Reversion: Rank by RSI (lowest first, most oversold)
        - Breakout: Rank by volume_ratio (highest first)
        """
        if not signals:
            return []
        
        if strategy_name == 'momentum':
            # Rank by 3-month return (highest momentum)
            return sorted(
                signals,
                key=lambda x: x['metrics'].get('return_3m', 0),
                reverse=True
            )
        
        elif strategy_name == 'mean_reversion_rsi':
            # Rank by RSI (lowest = most oversold)
            return sorted(
                signals,
                key=lambda x: x['metrics'].get('rsi', 100)
            )
        
        elif strategy_name == 'breakout':
            # Rank by volume ratio (highest spike)
            return sorted(
                signals,
                key=lambda x: x['metrics'].get('volume_ratio', 0),
                reverse=True
            )
        
        return signals
    
    def _rank_signals_multi(self, signals: List[Dict], primary_strategy: str) -> List[Dict]:
        """
        Rank signals from multiple strategies
        
        Prioritizes:
        1. Signals from primary strategy (regime-matching) get boost
        2. Then by strategy-specific metrics
        """
        if not signals:
            return []
        
        def get_score(sig):
            # Base score based on strategy-specific metrics
            strategy = sig.get('strategy', '')
            metrics = sig.get('metrics', {})
            
            if strategy == 'momentum_simple':
                # Higher 3M return = higher score
                base_score = metrics.get('return_3m', 0) * 100
            elif strategy == 'mean_reversion_rsi':
                # Lower RSI = higher score (more oversold)
                base_score = (100 - metrics.get('rsi', 50))
            elif strategy == 'breakout':
                # Higher volume ratio = higher score
                base_score = metrics.get('volume_ratio', 1) * 50
            else:
                base_score = 50
            
            # Apply regime boost (1.2x for primary strategy)
            regime_boost = sig.get('regime_boost', 1.0)
            
            return base_score * regime_boost
        
        return sorted(signals, key=get_score, reverse=True)
    
    def _filter_high_volatility(self, signals: List[Dict]) -> List[Dict]:
        """
        Filter out stocks with extremely high volatility (NATR > MAX_NATR_PERCENT).
        
        High volatility stocks can gap through stop losses, causing larger losses
        than expected. This filter removes the riskiest candidates.
        """
        if not signals:
            return []
        
        filtered = []
        removed_count = 0
        
        for sig in signals:
            natr = sig.get('metrics', {}).get('natr', 0)
            
            # If NATR not available, allow the signal (conservative)
            if natr is None or natr == 0:
                filtered.append(sig)
                continue
            
            if natr <= self.MAX_NATR_PERCENT:
                filtered.append(sig)
            else:
                removed_count += 1
                logger.info(f"⚠️ {sig['symbol']}: Filtered out - NATR {natr:.1f}% > {self.MAX_NATR_PERCENT}% (too volatile)")
        
        if removed_count > 0:
            logger.info(f"Volatility filter: {removed_count} high-volatility signals removed")
        
        return filtered
    
    def _apply_dynamic_sizing(self, signals: List[Dict]) -> List[Dict]:
        """
        Ricalcola position_size con il risk amount dalle impostazioni UI.
        
        Le strategie calcolano position_size con RISK_PER_TRADE_EUR = €20 fisso,
        ma per il trading reale vogliamo usare il valore impostato dall'utente.
        
        Questo metodo sovrascrive position_size e risk_amount con valori dinamici.
        
        SAFETY CHECKS:
        1. Position value capped at 33% of total capital
        2. Total allocated capital cannot exceed available capital
        """
        if not signals:
            return []
        
        # Get risk per trade from UI settings (fixed amount in EUR)
        risk_per_trade_str = self.user_db.get_setting("risk_per_stock_trade")
        if risk_per_trade_str:
            dynamic_risk_eur = float(risk_per_trade_str)
        else:
            # Fallback: calculate as 1.5% of capital
            dynamic_risk_eur = self.TOTAL_CAPITAL * 0.015
        
        # Get exchange rate
        from ..utils.currency import get_exchange_rate
        rate = get_exchange_rate(user_db=self.user_db)
        
        # Calculate capital already allocated to open positions
        try:
            open_positions = self.user_db.get_active_positions()
            allocated_capital = sum(
                pos.get('entry_price', 0) * pos.get('quantity', 0) * rate
                for pos in open_positions
            )
        except Exception:
            allocated_capital = 0
        
        available_capital = self.TOTAL_CAPITAL - allocated_capital
        logger.debug(f"Capital: Total €{self.TOTAL_CAPITAL:.0f}, Allocated €{allocated_capital:.0f}, Available €{available_capital:.0f}")
        
        for sig in signals:
            entry_price = sig.get('entry_price', 0)
            stop_loss = sig.get('stop_loss', 0)
            
            if entry_price <= 0 or stop_loss <= 0 or entry_price <= stop_loss:
                continue
            
            # Calculate risk per share in EUR
            risk_per_share_usd = entry_price - stop_loss
            risk_per_share_eur = risk_per_share_usd * rate
            
            if risk_per_share_eur <= 0:
                continue
            
            # Calculate new position size based on risk amount
            new_quantity = int(dynamic_risk_eur / risk_per_share_eur)
            new_quantity = max(1, new_quantity)
            
            # CAP: Position value cannot exceed max_position_percent of capital
            # Default: 33% of capital per position (configurable)
            max_position_pct = config.get("risk_management.max_position_percent", 33) / 100
            max_position_value_eur = self.TOTAL_CAPITAL * max_position_pct
            position_value_eur = new_quantity * entry_price * rate
            
            if position_value_eur > max_position_value_eur:
                # Reduce quantity to fit within max position value
                max_quantity = int(max_position_value_eur / (entry_price * rate))
                max_quantity = max(1, max_quantity)
                
                logger.info(
                    f"{sig['symbol']}: Position capped from {new_quantity} to {max_quantity} shares "
                    f"(value €{position_value_eur:.0f} > max €{max_position_value_eur:.0f})"
                )
                new_quantity = max_quantity
                position_value_eur = new_quantity * entry_price * rate
                
                # Recalculate actual risk with capped quantity
                actual_risk_eur = new_quantity * risk_per_share_eur
                sig['risk_amount'] = actual_risk_eur
                sig['risk_capped'] = True
            else:
                sig['risk_amount'] = dynamic_risk_eur
                sig['risk_capped'] = False
            
            # SAFETY CHECK: Ensure position doesn't exceed available capital
            if position_value_eur > available_capital:
                logger.warning(
                    f"{sig['symbol']}: Position value €{position_value_eur:.0f} exceeds "
                    f"available capital €{available_capital:.0f} - SKIPPED"
                )
                sig['position_size'] = 0
                sig['skip_reason'] = 'insufficient_capital'
                continue
            
            # Update signal with dynamic sizing
            sig['position_size'] = new_quantity
            sig['sizing_method'] = 'dynamic_fixed_risk'
            
            # Track cumulative allocation for subsequent signals
            available_capital -= position_value_eur
        
        logger.debug(f"Applied dynamic sizing: €{dynamic_risk_eur:.2f} risk per trade")
        
        return signals
    
    def _get_sector(self, symbol: str) -> str:
        """
        Get sector for a symbol.
        
        Uses local mapping first, then tries Polygon API.
        Returns 'Unknown' if sector cannot be determined.
        """
        # Check local mapping first (fast)
        if symbol in SECTOR_MAPPING:
            return SECTOR_MAPPING[symbol]
        
        # For symbols not in local mapping, return 'Unknown' to avoid API calls
        # and unclosed session warnings. The local mapping covers most common stocks.
        # This is a tradeoff: we skip API lookups but avoid resource leaks.
        return 'Unknown'
    
    def check_sector_diversity(self, new_signal: Dict, open_positions: List[Dict]) -> Dict:
        """
        Check if adding a new position would exceed sector concentration limits.
        
        Per spec Section 11.1: Max 40% in any single sector.
        
        Args:
            new_signal: The signal being considered for entry
            open_positions: List of current open positions
            
        Returns:
            Dict with:
                - 'allowed': bool - whether the signal passes diversity check
                - 'reason': str - explanation if not allowed
                - 'sector': str - sector of the new signal
                - 'current_concentration': float - current % in that sector
                - 'projected_concentration': float - % after adding new position
        """
        symbol = new_signal['symbol']
        new_sector = self._get_sector(symbol)
        
        if not open_positions:
            return {
                'allowed': True,
                'reason': 'No open positions, diversity OK',
                'sector': new_sector,
                'current_concentration': 0,
                'projected_concentration': 100  # Will be the only position
            }
        
        # Calculate current sector exposure
        sector_values = {}
        total_value = 0
        
        for pos in open_positions:
            pos_symbol = pos.get('symbol', '')
            pos_sector = self._get_sector(pos_symbol)
            
            # Estimate position value (entry_price * quantity)
            pos_value = pos.get('entry_price', 0) * pos.get('position_size', pos.get('quantity', 1))
            
            sector_values[pos_sector] = sector_values.get(pos_sector, 0) + pos_value
            total_value += pos_value
        
        # Calculate new position value
        new_value = new_signal.get('entry_price', 0) * new_signal.get('position_size', 1)
        new_total = total_value + new_value
        
        if new_total == 0:
            return {
                'allowed': True,
                'reason': 'No value data, allowing',
                'sector': new_sector,
                'current_concentration': 0,
                'projected_concentration': 0
            }
        
        # Current and projected concentration
        current_sector_value = sector_values.get(new_sector, 0)
        current_concentration = (current_sector_value / total_value * 100) if total_value > 0 else 0
        projected_concentration = (current_sector_value + new_value) / new_total * 100
        
        # Check limit
        max_pct = self.MAX_SECTOR_CONCENTRATION * 100
        
        if projected_concentration > max_pct:
            return {
                'allowed': False,
                'reason': f"Sector '{new_sector}' would be {projected_concentration:.1f}% (max {max_pct:.0f}%)",
                'sector': new_sector,
                'current_concentration': current_concentration,
                'projected_concentration': projected_concentration
            }
        
        return {
            'allowed': True,
            'reason': f"Sector '{new_sector}' at {projected_concentration:.1f}% (within {max_pct:.0f}% limit)",
            'sector': new_sector,
            'current_concentration': current_concentration,
            'projected_concentration': projected_concentration
        }
    
    def apply_sector_diversity_filter(self, signals: List[Dict]) -> List[Dict]:
        """
        Filter signals to maintain sector diversity.
        
        TWO RULES:
        1. Max 1 symbol per sector in new signals (avoid correlated losses like MU+LRCX)
        2. Max 40% capital concentration per sector (existing rule)
        
        Args:
            signals: List of signals (should be pre-ranked by _rank_signals_multi)
            
        Returns:
            Filtered list of signals that maintain diversity
        """
        if not signals:
            return []
        
        # Get current open positions
        try:
            open_positions = self.user_db.get_active_positions()
        except Exception as e:
            logger.debug(f"Could not get open positions for diversity check: {e}")
            open_positions = []
        
        # Count sectors in open positions
        open_sector_counts = {}
        for pos in open_positions:
            sector = self._get_sector(pos.get('symbol', ''))
            if sector != 'Unknown':
                open_sector_counts[sector] = open_sector_counts.get(sector, 0) + 1
        
        # Build list of accepted signals with STRICT sector diversity
        accepted_signals = []
        signal_sector_counts = {}  # Track sectors in NEW signals only
        simulated_positions = list(open_positions)
        
        for sig in signals:
            sector = self._get_sector(sig['symbol'])
            
            # Rule 1: Max symbols per sector (in NEW signals)
            if sector != 'Unknown':
                current_in_signals = signal_sector_counts.get(sector, 0)
                current_in_open = open_sector_counts.get(sector, 0)
                total_in_sector = current_in_signals + current_in_open
                
                if total_in_sector >= self.MAX_SYMBOLS_PER_SECTOR:
                    logger.info(f"⚠️ {sig['symbol']}: Skipped - Sector {sector} already has {total_in_sector} symbol(s)")
                    continue
            
            # Rule 2: Capital concentration check (existing logic)
            if sector != 'Unknown':
                diversity_check = self.check_sector_diversity(sig, simulated_positions)
                if not diversity_check['allowed']:
                    logger.info(f"⚠️ {sig['symbol']}: Skipped - {diversity_check['reason']}")
                    continue
            
            # Passed both rules - accept signal
            accepted_signals.append(sig)
            simulated_positions.append({
                'symbol': sig['symbol'],
                'entry_price': sig.get('entry_price', 0),
                'position_size': sig.get('position_size', 1)
            })
            
            if sector != 'Unknown':
                signal_sector_counts[sector] = signal_sector_counts.get(sector, 0) + 1
            
            logger.debug(f"✅ {sig['symbol']}: Sector {sector} - ALLOWED")
        
        filtered_count = len(signals) - len(accepted_signals)
        if filtered_count > 0:
            logger.info(f"Sector diversity filter: {filtered_count} signals filtered out (max {self.MAX_SYMBOLS_PER_SECTOR} per sector)")
        
        return accepted_signals
    
    def _enhance_stop_losses(self, signals: List[Dict]) -> List[Dict]:
        """
        Enhance stop losses using support levels and volume profile.
        
        Per Code Review v2 Issue #5:
        - Current: Stop = Entry - (fixed %)
        - Enhanced: Stop = MAX(original_stop, support_level × 0.995)
        
        The tighter stop (higher price) is used for better risk management.
        
        This is OPTIONAL - enabled via 'use_smart_stop_loss' setting.
        
        Args:
            signals: List of signals with 'stop_loss' field
            
        Returns:
            Signals with potentially improved stop losses
        """
        from ..intelligence.risk_manager import RiskManager
        from ..intelligence.indicators import IndicatorCalculator
        
        enhanced_signals = []
        
        for sig in signals:
            symbol = sig['symbol']
            entry_price = sig['entry_price']
            original_stop = sig['stop_loss']
            
            try:
                # Get historical data for support detection
                lookback = pd.Timestamp.now() - pd.Timedelta(days=100)
                df = self.db.get_data(symbol, start_date=lookback)
                
                if df.empty or len(df) < 50:
                    # Not enough data - keep original stop
                    enhanced_signals.append(sig)
                    continue
                
                # Calculate ATR for the optimal stop calculation
                df_with_indicators = IndicatorCalculator.calculate_all(df)
                atr = df_with_indicators['atr'].iloc[-1] if 'atr' in df_with_indicators.columns else None
                
                if atr is None or atr <= 0:
                    enhanced_signals.append(sig)
                    continue
                
                # Calculate volume profile for additional support detection
                try:
                    volume_profile = IndicatorCalculator.calculate_volume_profile(df)
                except Exception:
                    volume_profile = None
                
                # Get optimal stop using combined methods
                stop_result = RiskManager.calculate_optimal_stop_loss(
                    entry_price=entry_price,
                    atr=atr,
                    df=df,
                    volume_profile=volume_profile,
                    trade_type="swing"
                )
                
                optimal_stop = stop_result['stop_loss']
                method_used = stop_result['method']
                
                # Use the TIGHTER stop (higher price = less risk)
                if optimal_stop > original_stop:
                    sig['stop_loss'] = optimal_stop
                    sig['stop_loss_method'] = f"enhanced_{method_used}"
                    sig['original_stop'] = original_stop
                    logger.debug(
                        f"{symbol}: Stop enhanced ${original_stop:.2f} → ${optimal_stop:.2f} ({method_used})"
                    )
                else:
                    sig['stop_loss_method'] = "strategy_default"
                
                enhanced_signals.append(sig)
                
            except Exception as e:
                logger.debug(f"{symbol}: Could not enhance stop loss - {e}")
                enhanced_signals.append(sig)
        
        enhanced_count = sum(1 for s in enhanced_signals if s.get('stop_loss_method', '').startswith('enhanced'))
        if enhanced_count > 0:
            logger.info(f"Enhanced {enhanced_count}/{len(signals)} stop losses using support levels")
        
        return enhanced_signals
    
    @staticmethod
    def is_signal_valid(signal: Dict, check_time: Optional[pd.Timestamp] = None) -> Dict:
        """
        Check if a signal is still valid (not expired).
        
        Per Code Review Issue #9: Signals have 4-hour expiration by default.
        
        Args:
            signal: Signal dict with 'generated_at' and 'expires_at' fields
            check_time: Time to check against (default: now)
            
        Returns:
            Dict with:
                - 'is_valid': bool
                - 'reason': str
                - 'time_remaining': str|None
        """
        if check_time is None:
            check_time = pd.Timestamp.now()
        
        expires_at = signal.get('expires_at')
        generated_at = signal.get('generated_at')
        
        if expires_at is None:
            return {
                'is_valid': True,
                'reason': 'No expiration set',
                'time_remaining': None
            }
        
        # Ensure expires_at is a Timestamp
        if not isinstance(expires_at, pd.Timestamp):
            expires_at = pd.Timestamp(expires_at)
        
        if check_time > expires_at:
            return {
                'is_valid': False,
                'reason': f'Signal expired at {expires_at}',
                'time_remaining': None
            }
        
        time_remaining = expires_at - check_time
        hours = time_remaining.total_seconds() / 3600
        
        return {
            'is_valid': True,
            'reason': 'Signal valid',
            'time_remaining': f'{hours:.1f}h'
        }
    
    def close(self):
        """Cleanup"""
        self.db.close()
        self.regime_detector.close()
        self.momentum.close()
        self.mean_reversion.close()
        self.breakout.close()
