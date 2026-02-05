# TRADING SYSTEM SPECIFICATION DOCUMENT

**Semi-Automatic Short-Term US Equities Trading Platform**

---

| Field | Detail |
|---|---|
| Version | 1.0 |
| Date | February 2, 2026 |
| Status | Draft |
| Classification | Confidential |
| Broker | Trade Republic |
| Data Provider | Polygon.io (5-year history, 15-min delayed) |

> *This document defines the complete technical and strategic specification for a semi-automatic trading system designed for short-term operations on US equities. It serves as the blueprint for development, testing, and deployment.*

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Investor Profile & Capital Plan](#2-investor-profile--capital-plan)
3. [System Architecture](#3-system-architecture)
4. [Module 1: Market Scanner](#4-module-1-market-scanner)
5. [Module 2: Technical Analyzer](#5-module-2-technical-analyzer)
6. [Module 3: Signal Scoring Engine](#6-module-3-signal-scoring-engine)
7. [Module 4: Risk Management](#7-module-4-risk-management)
8. [Module 5: Dashboard & Alerts](#8-module-5-dashboard--alerts)
9. [Backtesting Framework](#9-backtesting-framework)
10. [Trade Republic Integration](#10-trade-republic-integration)
11. [Development Roadmap](#11-development-roadmap)
12. [Risk Disclosure & Realistic Expectations](#12-risk-disclosure--realistic-expectations)
13. [Glossary](#13-glossary)
14. [Document Control](#14-document-control)

---

## 1. Executive Summary

### 1.1 Project Overview

This project aims to build a semi-automatic trading system that analyzes the entire US equity market, identifies high-probability short-term trading opportunities, and delivers clear, actionable signals for manual execution on Trade Republic. The system acts as the analytical brain: scanning markets, computing technical indicators, scoring setups, managing risk, and recommending precise entries, exits, stop-losses, and position sizes. The operator executes the trades manually based on the system's recommendations.

### 1.2 Core Philosophy

> **The first rule of making money is not losing it.**

This system is built around capital preservation as the highest priority. Every component, from the multi-indicator scoring engine to the dynamic position sizing, is designed to protect capital first and seek alpha second. The system reduces exposure automatically during losing streaks, enforces strict per-trade risk limits, and never recommends overleveraged positions.

### 1.3 Key Specifications at a Glance

| Parameter | Value |
|---|---|
| Target Market | All US equities (NYSE, NASDAQ, AMEX) |
| Trading Style | Short-term: Intraday & Swing (1–5 days) |
| Execution Mode | Semi-automatic (system signals, manual execution) |
| Initial Capital | €1,000 |
| Monthly Contribution | €1,000 |
| Max Concurrent Positions | 3–5 |
| Risk Per Trade | ≤2% of account equity |
| Target Return | ~7% monthly (aspirational) |
| Leverage | None |
| Broker | Trade Republic |
| Data Provider | Polygon.io (5-year historical, 15-min delayed quotes) |
| Paper Trading Phase | 1 month minimum |

---

## 2. Investor Profile & Capital Plan

### 2.1 Financial Profile

| Item | Detail |
|---|---|
| Starting Capital | €1,000 |
| Recurring Deposit | €1,000/month from salary |
| Income Source | Salaried employment (stable) |
| Experience Level | Strong theoretical knowledge; transitioning to practice |
| Availability | 2–3 checks per day, flexible hours |
| Reinvestment Policy | 100% profit reinvestment (compound growth) |

### 2.2 Capital Growth Projection (Compound Model)

The table below shows three scenarios over 12 months, assuming €1,000/month deposits and full reinvestment. These are projections, not guarantees. Markets are inherently unpredictable and past performance does not indicate future results.

| Month | Deposits (€) | Conservative (2%/mo) | Moderate (5%/mo) | Aspirational (7%/mo) |
|---|---|---|---|---|
| 1 | 2,000 | 2,040 | 2,100 | 2,140 |
| 3 | 4,000 | 4,244 | 4,541 | 4,714 |
| 6 | 7,000 | 7,869 | 8,802 | 9,437 |
| 9 | 10,000 | 11,818 | 13,868 | 15,396 |
| 12 | 13,000 | 16,117 | 19,933 | 23,012 |

> ⚠️ **Important:** The 7% monthly target (~125% annualized) is extremely aggressive. Top-performing hedge funds average 15–30% annually. This target should be treated as an aspirational ceiling, not an expectation. A realistic starting goal is 2–5% monthly, which still represents exceptional performance.

---

## 3. System Architecture

### 3.1 High-Level Architecture

The system is composed of five major modules that operate in a sequential pipeline:

| Module | Function | Input | Output |
|---|---|---|---|
| Market Scanner | Filters the full US market to a watchlist | Polygon.io full ticker list | 50–100 candidate stocks |
| Technical Analyzer | Computes 15+ indicators per ticker | Candidate stocks + OHLCV data | Indicator matrix per stock |
| Signal Scorer | Scores and ranks setups | Indicator matrix | Ranked opportunity list |
| Risk Manager | Calculates position size, SL, TP | Top signals + account equity | Actionable trade plans |
| Dashboard | Displays signals and tracks portfolio | Trade plans + execution data | Visual interface |

### 3.2 Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Rich ecosystem for financial analysis |
| Data API | Polygon.io (free tier) | 5-year history, REST & WebSocket |
| Technical Analysis | pandas-ta / TA-Lib | Industry-standard indicator libraries |
| Backtesting | Backtrader / custom engine | Flexible strategy testing framework |
| Dashboard | Streamlit or Dash | Rapid prototyping, real-time updates |
| Database | SQLite (local) | Zero-config, portable, sufficient for scale |
| Scheduling | APScheduler / cron | Automated scan cycles |
| Notifications | Telegram Bot API / Email | Instant alerts on signal generation |
| Version Control | Git | Track strategy iterations |

### 3.3 Data Flow

```
Polygon.io API → Market Scanner → Technical Analyzer → Signal Scorer → Risk Manager → Dashboard + Alerts → Manual Execution on Trade Republic
```

---

## 4. Module 1: Market Scanner

### 4.1 Purpose

The Market Scanner reduces the universe of 8,000+ US-listed equities to a manageable watchlist of 50–100 stocks that meet minimum criteria for liquidity, volatility, and tradability. Only stocks that pass all filters are forwarded to the Technical Analyzer.

### 4.2 Filter Criteria

| Filter | Condition | Rationale |
|---|---|---|
| Minimum Price | > $5.00 | Avoids penny stocks; Trade Republic availability |
| Maximum Price | < $500 (adjustable) | Feasible position sizing with small capital |
| Avg. Daily Volume | > 500,000 shares | Ensures liquidity for clean entry/exit |
| Market Cap | > $500M | Filters micro-caps prone to manipulation |
| ATR (14-day) | > 1.5% of price | Sufficient volatility for short-term profit |
| Spread Estimate | < 0.3% of price | Minimizes Trade Republic spread impact |
| Exchange | NYSE, NASDAQ, AMEX | Major US exchanges only |
| Sector Exclusion | No OTC, ADR, SPAC shells | Avoids illiquid or speculative instruments |

### 4.3 Scan Frequency

The scanner runs at three intervals to balance freshness with API rate limits:

- **Pre-market scan (8:00 AM EST):** Full universe scan with overnight data. Generates the daily watchlist.
- **Midday refresh (12:30 PM EST):** Re-scores watchlist stocks with updated intraday data.
- **Post-market review (4:30 PM EST):** Final scan for swing trade setups based on closing data.

---

## 5. Module 2: Technical Analyzer

### 5.1 Indicator Suite

The system computes a comprehensive set of technical indicators across four categories. Using multiple indicators from different families reduces false signals and increases the reliability of confluence-based scoring.

#### 5.1.1 Trend Indicators

| Indicator | Parameters | Signal Logic |
|---|---|---|
| SMA (Simple Moving Average) | 20, 50, 200 periods | Price above SMA = bullish; crossovers signal trend changes |
| EMA (Exponential Moving Average) | 9, 21, 50 periods | Faster response to price; EMA crossover = momentum shift |
| MACD | 12, 26, 9 | MACD > Signal = bullish; histogram divergence = reversal |
| ADX (Average Directional Index) | 14 periods | ADX > 25 = trending; < 20 = ranging (avoid) |
| Ichimoku Cloud | 9, 26, 52 | Price above cloud = bullish; Tenkan/Kijun cross = entry |
| Parabolic SAR | 0.02, 0.2 | Dots below price = uptrend; flip = trend reversal |
| SuperTrend | 10, 3 | Price above band = bullish; confirms trend direction |

#### 5.1.2 Momentum Indicators

| Indicator | Parameters | Signal Logic |
|---|---|---|
| RSI (Relative Strength Index) | 14 periods | < 30 = oversold; > 70 = overbought; divergence = reversal |
| Stochastic Oscillator | 14, 3, 3 | %K/%D crossover in extreme zones = entry signal |
| Williams %R | 14 periods | < -80 = oversold; > -20 = overbought |
| CCI (Commodity Channel Index) | 20 periods | > +100 = overbought; < -100 = oversold |
| ROC (Rate of Change) | 12 periods | Positive = bullish momentum; zero-line cross = signal |
| MFI (Money Flow Index) | 14 periods | Volume-weighted RSI; confirms RSI signals |

#### 5.1.3 Volatility Indicators

| Indicator | Parameters | Signal Logic |
|---|---|---|
| Bollinger Bands | 20, 2 | Price at lower band + RSI < 30 = buy signal |
| ATR (Average True Range) | 14 periods | Used for dynamic stop-loss and position sizing |
| Keltner Channels | 20, 1.5 | Squeeze detection when inside Bollinger Bands |
| Donchian Channels | 20 periods | Breakout above upper = long entry signal |

#### 5.1.4 Volume Indicators

| Indicator | Parameters | Signal Logic |
|---|---|---|
| OBV (On-Balance Volume) | Cumulative | Rising OBV + rising price = confirmed trend |
| VWAP | Session | Price > VWAP = bullish intraday bias |
| Volume SMA | 20 periods | Current vol > 1.5x avg = significant move |
| A/D Line | Cumulative | Divergence from price = potential reversal |
| CMF (Chaikin Money Flow) | 20 periods | > 0 = buying pressure; < 0 = selling |

---

## 6. Module 3: Signal Scoring Engine

### 6.1 Scoring Methodology

Each stock receives a composite score from 0 to 100 based on indicator confluence. The system does not rely on any single indicator. Instead, it weights signals across all four indicator families and only recommends trades when multiple independent confirmations align.

### 6.2 Category Weights

| Category | Weight | Max Points | Rationale |
|---|---|---|---|
| Trend Alignment | 35% | 35 | Trend is the strongest edge in short-term trading |
| Momentum Confirmation | 25% | 25 | Confirms the trend has energy behind it |
| Volume Validation | 20% | 20 | Separates real moves from noise |
| Volatility Context | 10% | 10 | Ensures enough range for profit targets |
| Pattern Recognition | 10% | 10 | Candlestick and chart pattern bonus |

### 6.3 Signal Thresholds

| Score Range | Classification | Action |
|---|---|---|
| **80–100** | Strong Signal | Primary recommendation; immediate alert sent |
| **65–79** | Moderate Signal | Secondary watchlist; alert if score improves |
| **50–64** | Weak Signal | Monitor only; no trade recommended |
| **0–49** | No Signal | Ignored; filtered from dashboard |

### 6.4 Strategy Selection

The system evaluates multiple strategy types for each candidate and recommends the one with the highest expected value:

| Strategy | Description | Best Market Condition |
|---|---|---|
| Momentum Breakout | Entry on volume-confirmed break of resistance | Trending market, high ADX |
| Mean Reversion | Buy oversold bounces at support levels | Ranging market, low ADX |
| EMA Crossover | Entry on fast/slow EMA cross with volume | Early trend formation |
| Bollinger Squeeze | Entry after volatility compression breakout | Low volatility transitioning to high |
| VWAP Reversion | Intraday entry on VWAP bounce with volume | Intraday, high-volume stocks |
| Gap Fill | Trade gaps that are likely to fill | Post-earnings or news events |

The system ranks strategies by backtested expected value and presents the top recommendation along with alternatives. The operator makes the final decision.

---

## 7. Module 4: Risk Management

> ***This is the most critical module in the system. Without disciplined risk management, no strategy can survive the inevitable losing streaks that are part of all trading.***

### 7.1 Per-Trade Risk Rules

| Rule | Parameter | Description |
|---|---|---|
| Max Risk Per Trade | 2% of equity | Maximum capital at risk on any single position |
| Position Size Formula | Risk / (Entry - SL) | Shares = (Equity × 0.02) / (Entry Price - Stop Loss) |
| Max Position Value | 33% of equity | No single stock exceeds 1/3 of account |
| Max Concurrent Positions | 3–5 | Limits correlation risk and monitoring burden |
| Max Sector Exposure | 40% of equity | Prevents sector concentration blow-up |

### 7.2 Dynamic Stop-Loss Calculation

Stop-losses are calculated dynamically to maximize the reward-to-risk ratio while respecting market volatility:

- **ATR-Based Stop:** SL = Entry Price - (ATR(14) × Multiplier). Default multiplier: 1.5 for swing trades, 1.0 for intraday.
- **Support-Based Stop:** SL placed below the nearest significant support level identified from price action.
- **Trailing Stop:** Once a trade is in profit by 1× ATR, the stop trails at 1.5× ATR below the highest price reached.
- **Final SL Selection:** The system picks the tighter of ATR-based and support-based, ensuring the reward:risk ratio is at least 2:1. If no setup achieves 2:1, the trade is rejected.

### 7.3 Take-Profit Targets

| Target | Calculation | Action |
|---|---|---|
| TP1 (Partial) | Entry + 1.5× ATR | Sell 50% of position; move SL to breakeven |
| TP2 (Full) | Entry + 3× ATR | Close remaining position |
| Extended TP | Next major resistance | Optional: trail stop instead of fixed target |

### 7.4 Drawdown Protection

The system automatically reduces exposure during losing periods to protect capital:

| Condition | Action | Recovery Trigger |
|---|---|---|
| 3 consecutive losses | Reduce position size to 1% risk | 2 consecutive wins |
| 5 consecutive losses | Reduce to 1 position max | 3 consecutive wins |
| Account down 6% in a month | Pause live trading; paper trade only | 1 week profitable paper trading |
| Account down 10% in a month | Stop all trading; full system review | Complete strategy review + backtest |

### 7.5 Trade Republic Cost Model

Trade Republic charges no traditional commissions, but costs still exist and must be factored into every trade:

| Cost Type | Estimate | Impact on Strategy |
|---|---|---|
| Order Fee | €1 per trade | Significant on small positions; favor larger, fewer trades |
| Spread (Bid-Ask) | 0.05%–0.30% | Wider on less liquid stocks; scanner filters for tight spreads |
| FX Conversion | ~0.25% (EUR→USD) | Applied on every US stock trade; reduces effective return |
| Slippage (15-min delay) | ~0.1%–0.5% | Data is delayed; use limit orders, not market orders |

> ⚠️ **Estimated round-trip cost per trade: 0.5%–1.2%.** This means the system must generate setups with expected moves of at least 2–3% to be profitable after costs. The signal scorer incorporates these costs into its expected value calculations.

---

## 8. Module 5: Dashboard & Alerts

### 8.1 Dashboard Layout

The dashboard is the operator's primary interface. It must be scannable in under 30 seconds:

#### 8.1.1 Panel: Active Signals

- **Content:** Top 5 ranked signals with score, strategy, entry, SL, TP, position size, expected R:R ratio.
- **Color Coding:** Green (strong, 80+), Blue (moderate, 65–79), Gray (weak/expired).
- **Action Buttons:** "Accept" (logs trade in journal), "Dismiss" (archives signal).

#### 8.1.2 Panel: Open Positions

- **Content:** Current holdings with entry price, current price, unrealized P&L, time held, stop-loss status.
- **Alerts:** Flashing indicator if any position is near its stop-loss or take-profit level.

#### 8.1.3 Panel: Performance Metrics

- **Content:** Daily/weekly/monthly P&L, win rate, average R:R, total trades, equity curve chart.
- **Comparison:** Benchmark against S&P 500 to measure alpha generated.

#### 8.1.4 Panel: Risk Monitor

- **Content:** Current exposure (% of equity), sector distribution, drawdown level, consecutive loss counter.
- **Warnings:** Red banner if any risk limit is breached.

### 8.2 Alert System

| Alert Type | Channel | Trigger |
|---|---|---|
| New Strong Signal (80+) | Telegram + Dashboard | Signal scorer produces score ≥ 80 |
| Stop-Loss Approaching | Telegram | Price within 0.5% of SL level |
| Take-Profit Hit | Telegram + Dashboard | Price reaches TP1 or TP2 |
| Risk Limit Breach | Telegram (urgent) | Any drawdown protection rule triggered |
| Daily Summary | Email | End-of-day report: P&L, open positions, tomorrow watchlist |

---

## 9. Backtesting Framework

### 9.1 Backtesting Rules

Backtesting is critical to validate strategies before risking real capital. However, backtests must be conducted with extreme care to avoid survivorship bias, look-ahead bias, and overfitting:

- **Data Period:** Minimum 3 years of historical data (from Polygon.io 5-year archive).
- **Walk-Forward Analysis:** Train on 70% of data, validate on 30%. Never optimize on the validation set.
- **Realistic Fills:** Add 0.1% slippage + estimated spread to every simulated entry and exit.
- **Cost Inclusion:** Include Trade Republic's €1 fee, FX conversion cost, and spread in all simulated P&L.
- **Survivorship Bias:** Include delisted stocks in the historical universe where available.
- **Market Regime Testing:** Test across bull (2021), bear (2022), and sideways (2023) markets separately.

### 9.2 Key Performance Metrics

| Metric | Target (Minimum) | Description |
|---|---|---|
| Win Rate | > 55% | Percentage of trades that are profitable |
| Avg. Win / Avg. Loss | > 1.5 | Average profit of winners vs. average loss of losers |
| Profit Factor | > 1.5 | Gross profits / gross losses |
| Max Drawdown | < 15% | Largest peak-to-trough decline in equity |
| Sharpe Ratio | > 1.0 | Risk-adjusted return; higher = better |
| Sortino Ratio | > 1.5 | Penalizes only downside volatility |
| Avg. Trade Duration | 1–5 days | Confirms short-term strategy alignment |
| Trades Per Month | 15–40 | Enough data to be statistically meaningful |
| Recovery Factor | > 3.0 | Net profit / max drawdown |

### 9.3 Paper Trading Validation

The system must pass a 1-month paper trading phase before any real money is deployed:

| Criteria | Requirement | Notes |
|---|---|---|
| Duration | Minimum 30 calendar days | Must include at least 20 trading days |
| Trade Count | Minimum 20 trades | Enough for statistical significance |
| Win Rate | > 50% | Must demonstrate positive edge |
| Profit Factor | > 1.3 | Slightly relaxed from backtest target |
| Max Drawdown | < 10% | Tighter than backtest due to smaller sample |
| Execution Gap | < 0.3% | Difference between signal price and simulated fill |

---

## 10. Trade Republic Integration

### 10.1 Platform Constraints

Trade Republic does not offer a trading API. All order execution must be performed manually by the operator. The system is designed to accommodate this constraint:

| Constraint | Impact | Mitigation |
|---|---|---|
| No API | Cannot automate execution | Clear, copy-paste-ready signals with exact parameters |
| 15-min delayed data | Entry/exit prices may drift | Use limit orders exclusively; buffer signals by 0.2% |
| Limited order types | No OCO (one-cancels-other) | Set SL manually after entry; alerts remind if missed |
| EUR-denominated account | FX cost on every US trade | Factor 0.25% FX cost into all calculations |
| Market hours only | No pre/post-market trading | Signal timing accounts for market open/close dynamics |
| Spread variability | Wider spreads on illiquid names | Scanner filters for high-volume, tight-spread stocks |

### 10.2 Execution Workflow

When the system generates a trade signal, the operator follows this workflow:

1. **Signal Alert:** Telegram/dashboard notification with full trade details.
2. **Validation:** Operator reviews signal score, checks current price on Trade Republic.
3. **Execution:** Place LIMIT order at recommended entry price (not market order).
4. **Stop-Loss:** Immediately set stop-loss order at the SL price provided by the system.
5. **Logging:** Confirm execution in the dashboard (actual fill price, time, fees).
6. **Monitoring:** System continues to track the position and alerts at TP1/TP2/SL levels.

---

## 11. Development Roadmap

| Phase | Duration | Deliverables | Success Criteria |
|---|---|---|---|
| **Phase 1: Foundation** | Weeks 1–2 | Polygon.io integration, data pipeline, SQLite schema, basic scanner with volume/price filters | Scanner returns 50–100 valid candidates daily |
| **Phase 2: Analysis Engine** | Weeks 3–4 | Full indicator suite (22+ indicators), signal scorer with weighted scoring, strategy evaluator | Indicators compute correctly against known values |
| **Phase 3: Risk Module** | Week 5 | Position sizing, dynamic SL/TP, drawdown protection, Trade Republic cost model | Risk calculations match manual spreadsheet verification |
| **Phase 4: Backtesting** | Weeks 6–7 | Backtrader integration, walk-forward testing, regime analysis, performance reporting | Backtest meets minimum metric thresholds (Section 9.2) |
| **Phase 5: Dashboard** | Week 8 | Streamlit dashboard with all 4 panels, Telegram bot alerts, email daily summary | Dashboard loads in < 3 seconds; alerts delivered in < 30 seconds |
| **Phase 6: Paper Trading** | Weeks 9–12 | Live paper trading with full system, trade journal, daily review process | Meets paper trading criteria (Section 9.3) |
| **Phase 7: Go Live** | Week 13+ | Transition to real capital (€1,000), gradual ramp-up, weekly performance reviews | First month live: no drawdown protection triggers |

### 11.1 Post-Launch Enhancements

After the core system is live, the following enhancements are planned in priority order:

- **Machine Learning Layer:** Train a gradient-boosted model on historical signal outcomes to optimize category weights dynamically.
- **Sentiment Analysis:** Integrate news sentiment from free APIs (e.g., Finnhub) as an additional scoring factor.
- **Sector Rotation Model:** Detect which sectors are in favor and bias the scanner toward them.
- **Correlation Analysis:** Ensure open positions are not correlated (e.g., avoid holding 3 tech stocks simultaneously).
- **Broker Migration:** Evaluate IBKR or similar for API-based execution once capital justifies the fees.

---

## 12. Risk Disclosure & Realistic Expectations

### 12.1 Inherent Risks

Trading involves substantial risk of financial loss. This section exists to ensure full transparency about what the system can and cannot do:

- **Market Risk:** Stock prices can gap down overnight, blow through stop-losses, and cause losses exceeding the 2% per-trade limit.
- **Execution Risk:** Manual execution introduces delay; prices may move between signal generation and order placement.
- **Data Risk:** 15-minute delayed data means signals are based on stale prices; fast-moving stocks may gap past entry levels.
- **Model Risk:** Backtested strategies may not perform in live markets due to changing market conditions, regime shifts, or overfitting.
- **Liquidity Risk:** During market stress, spreads widen and orders may not fill at expected prices.
- **Psychological Risk:** Even with a system, the operator must resist overriding signals, revenge trading, or abandoning risk rules after losses.

### 12.2 Return Expectations

It is essential to calibrate expectations with market reality:

| Benchmark | Annualized Return | Context |
|---|---|---|
| S&P 500 (historical avg.) | ~10% | The default benchmark for any equity strategy |
| Top hedge funds (Renaissance) | ~30–60% | With billions in R&D, PhDs, and proprietary data |
| Successful day traders (top 5%) | ~30–100% | Full-time professionals with years of experience |
| This system (conservative) | ~25–60% | Realistic range; depends on market conditions |
| **This system (aspirational)** | **~125%** | **7%/month target; achievable in strong markets, not sustainable long-term** |

The 7% monthly target is used as an aspirational metric to push the system toward high-quality setups. The actual expectation should be 2–5% monthly, with the understanding that some months will be negative. The system is designed so that even at 2–3% monthly, the compound growth with €1,000/month contributions builds meaningful wealth over time.

### 12.3 Psychological Rules for the Operator

The system is only as good as the discipline of the person executing its signals:

- **Never override the stop-loss.** If the system says sell, sell. No hoping, no praying, no averaging down.
- **Never increase position size after a win.** Euphoria leads to oversizing leads to ruin.
- **Never revenge trade.** After a loss, the next trade must meet full scoring criteria.
- **Trust the system or fix it.** Either follow the signals or pause and improve the system. Never freestyle.
- **Review weekly, not per-trade.** Individual trade outcomes are noise. Weekly and monthly performance is signal.

---

## 13. Glossary

| Term | Definition |
|---|---|
| ATR | Average True Range; measures volatility over a period |
| Drawdown | Peak-to-trough decline in account equity |
| Equity Curve | Chart showing account value over time |
| OHLCV | Open, High, Low, Close, Volume — standard price data format |
| Position Sizing | Calculating how many shares to buy based on risk parameters |
| R:R Ratio | Reward-to-risk ratio; expected profit divided by expected loss |
| Sharpe Ratio | Risk-adjusted return metric; higher is better |
| Slippage | Difference between expected and actual execution price |
| Stop-Loss (SL) | Price level at which a losing position is automatically closed |
| Take-Profit (TP) | Price level at which a winning position is closed to lock in gains |
| Walk-Forward | Backtesting method that simulates real-time strategy development |
| Win Rate | Percentage of trades that result in a profit |

---

## 14. Document Control

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | February 2, 2026 | System Architect | Initial specification document |
