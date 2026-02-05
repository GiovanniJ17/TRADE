"""
Market Scanner - Quality Filters for Stock Screening
Per Trading System Specification v1.0 Section 4.2

Filter Criteria:
- Minimum Price: > $5.00 (avoids penny stocks)
- Maximum Price: < $500 (feasible position sizing)
- Avg. Daily Volume: > 500,000 shares (liquidity)
- Market Cap: > $500M (filters micro-caps)
- ATR (14-day): > 1.5% of price (sufficient volatility)
- Spread Estimate: < 0.3% of price (minimizes costs)
- Exchange: NYSE, NASDAQ, AMEX only
- Sector Exclusion: No OTC, ADR, SPAC shells
"""
import pandas as pd
from typing import List, Dict, Optional
from loguru import logger

from ..indicators import IndicatorCalculator
from ...utils.config import config


class StockScreener:
    """Apply quality filters to screen stocks per specification"""
    
    # Valid exchanges per spec
    VALID_EXCHANGES = {'XNYS', 'XNAS', 'XASE', 'NYSE', 'NASDAQ', 'AMEX', 'NYS', 'NAS', 'ASE'}
    
    # Valid security types (exclude OTC, ADR, SPAC, etc.)
    VALID_TYPES = {'CS', 'ETF'}  # Common Stock, ETF
    EXCLUDED_TYPES = {'ADRC', 'ADR', 'WARRANT', 'RIGHT', 'UNIT', 'SPAC', 'SP'}
    
    def __init__(self):
        """Initialize with configurable filter parameters"""
        self.filters = {
            # Price filters
            'min_price': config.get("filters.min_price", 5.0),
            'max_price': config.get("filters.max_price", 500.0),
            
            # Volume filter
            'min_avg_volume': config.get("filters.min_avg_volume", 500000),
            
            # Market cap filter
            'min_market_cap': config.get("filters.min_market_cap", 500000000),  # $500M
            
            # Volatility filters (NATR = ATR as % of price)
            'min_natr': config.get("filters.min_natr", 1.5),  # Min 1.5%
            'max_natr': config.get("filters.max_natr", 8.0),  # Max 8% (avoid crazy volatile)
            
            # Liquidity filters
            'min_dollar_volume': config.get("filters.min_dollar_volume", 5000000),  # $5M/day
            'max_spread_percent': config.get("filters.max_spread_percent", 0.3),  # 0.3%
            
            # Benchmark for market regime
            'benchmark_symbol': config.get("filters.benchmark_symbol", "SPY")
        }
        
        # Cache for ticker details (market cap, exchange, type)
        self._ticker_details_cache: Dict[str, Optional[Dict]] = {}
    
    def apply_filters(self, df: pd.DataFrame, symbol: str, 
                      ticker_details: Optional[Dict] = None) -> Dict:
        """
        Apply all quality filters to a stock.
        
        Args:
            df: OHLCV DataFrame with indicators
            symbol: Stock symbol
            ticker_details: Optional dict from Polygon Reference API with market_cap, exchange, type
        
        Returns:
            Dict with:
            - 'passed': bool - whether stock passes all filters
            - 'reasons': list of filter results
            - 'metrics': dict of computed values
        """
        if df.empty or len(df) < 20:
            return {
                'passed': False,
                'reasons': ['Insufficient data (need 20+ bars)'],
                'metrics': {}
            }
        
        # Calculate indicators if not present
        if 'dollar_volume' not in df.columns or 'natr' not in df.columns:
            df = IndicatorCalculator.calculate_all(df)
        
        latest = df.iloc[-1]
        reasons = []
        passed = True
        metrics = {}
        
        # ==================== PRICE FILTERS ====================
        
        # Filter 1: Minimum Price > $5
        current_price = latest['close']
        metrics['price'] = current_price
        
        if current_price < self.filters['min_price']:
            passed = False
            reasons.append(f"FAIL Price: ${current_price:.2f} < ${self.filters['min_price']:.2f} min (penny stock)")
        elif current_price > self.filters['max_price']:
            passed = False
            reasons.append(f"FAIL Price: ${current_price:.2f} > ${self.filters['max_price']:.2f} max (too expensive)")
        else:
            reasons.append(f"OK Price: ${current_price:.2f}")
        
        # ==================== VOLUME FILTERS ====================
        
        # Filter 2: Average Daily Volume > 500K shares
        avg_volume = df['volume'].tail(20).mean()
        metrics['avg_volume'] = avg_volume
        
        if avg_volume < self.filters['min_avg_volume']:
            passed = False
            reasons.append(f"FAIL Volume: {avg_volume:,.0f} < {self.filters['min_avg_volume']:,.0f} min shares")
        else:
            reasons.append(f"OK Volume: {avg_volume:,.0f} shares/day")
        
        # Filter 3: Dollar Volume > $5M/day
        avg_dollar_volume = df['dollar_volume'].tail(20).mean()
        metrics['avg_dollar_volume'] = avg_dollar_volume
        
        if avg_dollar_volume < self.filters['min_dollar_volume']:
            passed = False
            reasons.append(f"FAIL Liquidity: ${avg_dollar_volume:,.0f} < ${self.filters['min_dollar_volume']:,.0f}/day")
        else:
            reasons.append(f"OK Liquidity: ${avg_dollar_volume:,.0f}/day")
        
        # ==================== VOLATILITY FILTERS ====================
        
        # Filter 4: ATR (NATR) between 1.5% and 8%
        if pd.notna(latest.get('natr')):
            natr = latest['natr']
            metrics['natr'] = natr
            
            if natr < self.filters['min_natr']:
                passed = False
                reasons.append(f"FAIL Volatility: NATR {natr:.2f}% < {self.filters['min_natr']:.2f}% min (dead stock)")
            elif natr > self.filters['max_natr']:
                passed = False
                reasons.append(f"FAIL Volatility: NATR {natr:.2f}% > {self.filters['max_natr']:.2f}% max (too risky)")
            else:
                reasons.append(f"OK Volatility: NATR {natr:.2f}%")
        else:
            reasons.append("WARN Volatility: NATR not available")
            metrics['natr'] = None
        
        # ==================== SPREAD ESTIMATE ====================
        
        # Filter 5: Spread estimate < 0.3% (using high-low range as proxy)
        # Estimated spread = (High - Low) / Close as a rough proxy
        avg_range_pct = ((df['high'] - df['low']) / df['close']).tail(20).mean() * 100
        # Spread is typically ~10-20% of the daily range for liquid stocks
        estimated_spread = avg_range_pct * 0.15  # Conservative estimate
        metrics['estimated_spread'] = estimated_spread
        
        if estimated_spread > self.filters['max_spread_percent']:
            # Don't fail on spread alone, just warn
            reasons.append(f"WARN Spread: ~{estimated_spread:.2f}% > {self.filters['max_spread_percent']:.2f}% (may be wide)")
        else:
            reasons.append(f"OK Spread: ~{estimated_spread:.2f}%")
        
        # ==================== TICKER DETAILS FILTERS (if available) ====================
        
        if ticker_details:
            # Filter 6: Market Cap > $500M
            market_cap = ticker_details.get('market_cap')
            if market_cap is not None:
                metrics['market_cap'] = market_cap
                
                if market_cap < self.filters['min_market_cap']:
                    passed = False
                    reasons.append(f"FAIL Market Cap: ${market_cap/1e9:.2f}B < ${self.filters['min_market_cap']/1e9:.2f}B min")
                else:
                    reasons.append(f"OK Market Cap: ${market_cap/1e9:.2f}B")
            else:
                reasons.append("WARN Market Cap: not available")
            
            # Filter 7: Exchange (NYSE, NASDAQ, AMEX only)
            exchange = ticker_details.get('primary_exchange', '')
            metrics['exchange'] = exchange
            
            # Normalize exchange names
            exchange_upper = exchange.upper() if exchange else ''
            if not any(valid in exchange_upper for valid in self.VALID_EXCHANGES):
                if exchange:  # Only fail if we have exchange info
                    passed = False
                    reasons.append(f"FAIL Exchange: {exchange} (not NYSE/NASDAQ/AMEX)")
                else:
                    reasons.append("WARN Exchange: not available")
            else:
                reasons.append(f"OK Exchange: {exchange}")
            
            # Filter 8: Security Type (exclude OTC, ADR, SPAC, etc.)
            sec_type = ticker_details.get('type', '')
            metrics['type'] = sec_type
            
            if sec_type:
                if sec_type.upper() in self.EXCLUDED_TYPES:
                    passed = False
                    reasons.append(f"FAIL Type: {sec_type} (excluded: ADR/SPAC/etc)")
                elif sec_type.upper() in self.VALID_TYPES:
                    reasons.append(f"OK Type: {sec_type}")
                else:
                    # Unknown type - allow but warn
                    reasons.append(f"WARN Type: {sec_type} (unknown)")
        else:
            reasons.append("INFO Ticker details not available (market cap, exchange filters skipped)")
        
        return {
            'passed': passed,
            'reasons': reasons,
            'metrics': metrics
        }
    
    def apply_filters_batch(self, data_dict: Dict[str, pd.DataFrame],
                            ticker_details_dict: Optional[Dict[str, Dict]] = None) -> Dict[str, Dict]:
        """
        Apply filters to multiple symbols at once.
        
        Args:
            data_dict: Dict mapping symbol -> OHLCV DataFrame
            ticker_details_dict: Optional dict mapping symbol -> ticker details
        
        Returns:
            Dict mapping symbol -> filter results
        """
        results = {}
        
        for symbol, df in data_dict.items():
            ticker_details = None
            if ticker_details_dict:
                ticker_details = ticker_details_dict.get(symbol)
            
            results[symbol] = self.apply_filters(df, symbol, ticker_details)
        
        return results
    
    def validate_trade_economics(self, entry_price: float, quantity: int, 
                                 commission_cost: float, min_trade_value: float = None) -> Dict:
        """
        Validate if trade is economically viable after commissions.
        Per spec: Commission should be < 2% of trade value.
        
        Args:
            entry_price: Entry price per share
            quantity: Number of shares
            commission_cost: Total commission cost (entry + exit)
            min_trade_value: Minimum trade value (default from config)
        
        Returns:
            Dict with validation result
        """
        if min_trade_value is None:
            min_trade_value = config.get("risk.min_trade_value", 50.0)
        
        trade_value = entry_price * quantity
        commission_percent = (commission_cost / trade_value * 100) if trade_value > 0 else 100
        
        is_valid = (
            trade_value >= min_trade_value and
            commission_percent < 2.0  # Commission should be < 2% of trade value
        )
        
        return {
            'is_valid': is_valid,
            'trade_value': trade_value,
            'commission_percent': commission_percent,
            'reason': (
                f"Trade value ${trade_value:.2f}, Commission {commission_percent:.2f}%" 
                if is_valid else 
                f"Trade too small (${trade_value:.2f}) or commission too high ({commission_percent:.2f}%)"
            )
        }
    
    def check_market_regime(self, benchmark_df: pd.DataFrame) -> Dict:
        """
        Check market regime (bull/bear) based on benchmark.
        Used to apply stricter criteria in bear markets.
        
        Returns:
            Dict with 'regime', 'stricter_criteria' flag, and metrics
        """
        if benchmark_df.empty or len(benchmark_df) < 200:
            return {
                'regime': 'unknown',
                'stricter_criteria': False,
                'benchmark_price': None,
                'sma_200': None,
                'adx': None
            }
        
        # Calculate indicators if not present
        if 'sma_200' not in benchmark_df.columns:
            benchmark_df = IndicatorCalculator.calculate_all(benchmark_df)
        
        latest = benchmark_df.iloc[-1]
        sma_200 = latest.get('sma_200')
        adx = latest.get('adx')
        
        # Determine regime
        if pd.notna(sma_200):
            if latest['close'] > sma_200:
                regime = 'bull'
                stricter = False
            else:
                regime = 'bear'
                stricter = True  # Apply stricter criteria in bear market
        else:
            regime = 'unknown'
            stricter = False
        
        # ADX-based trend strength
        trend_strength = 'unknown'
        if pd.notna(adx):
            if adx > 25:
                trend_strength = 'strong'
            elif adx > 20:
                trend_strength = 'moderate'
            else:
                trend_strength = 'weak'
        
        return {
            'regime': regime,
            'stricter_criteria': stricter,
            'benchmark_price': float(latest['close']),
            'sma_200': float(sma_200) if pd.notna(sma_200) else None,
            'adx': float(adx) if pd.notna(adx) else None,
            'trend_strength': trend_strength
        }
    
    def get_filter_summary(self, filter_results: Dict[str, Dict]) -> Dict:
        """
        Generate summary statistics from filter results.
        
        Returns:
            Dict with counts and lists of passed/failed symbols
        """
        passed_symbols = []
        failed_symbols = []
        
        for symbol, result in filter_results.items():
            if result.get('passed', False):
                passed_symbols.append(symbol)
            else:
                failed_symbols.append(symbol)
        
        return {
            'total_screened': len(filter_results),
            'passed_count': len(passed_symbols),
            'failed_count': len(failed_symbols),
            'pass_rate': len(passed_symbols) / len(filter_results) * 100 if filter_results else 0,
            'passed_symbols': passed_symbols,
            'failed_symbols': failed_symbols
        }
