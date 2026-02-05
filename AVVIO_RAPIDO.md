# 🚀 GUIDA AVVIO RAPIDO

## ⚡ TEST VELOCE (2 minuti)

### Test Segnali Oggi
```bash
python scripts/test_portfolio_manager.py
```

**Output**:
- Regime mercato corrente
- Strategia selezionata
- Top segnali stock
- Capital allocation

**Usa**: Ogni 3-5 giorni per trading!

---

## 🖥️ DASHBOARD WEB

### Opzione 1 - Lancio Rapido
```bash
python run.py
```

### Opzione 2 - Via Main
```bash
python main.py ui
```

**Si apre**: Browser con UI interattiva

---

## 📋 SETUP INIZIALE (Prima Volta)

### 1. Installa Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configura API (Polygon.io)
Modifica `config/config.yaml`:
```yaml
data_provider:
  api_key: "TUA_API_KEY"
```

### 3. Scarica Benchmarks
```bash
python scripts/download_benchmarks.py
```

### 4. Scarica Watchlist
```bash
python main.py update --force-full
```

**Tempo**: ~5 minuti totali

---

## 🎯 COMANDI PRINCIPALI

### Test & Segnali
```bash
# Segnali oggi (RACCOMANDATO!)
python scripts/test_portfolio_manager.py

# Dashboard UI
python run.py

# Check regime SPY
python scripts/check_spy_regime.py
```

### Data Management
```bash
# Update incrementale
python main.py update

# Full download (5 anni)
python main.py update --force-full

# Solo benchmarks (SPY, QQQ)
python scripts/download_benchmarks.py
```

### Backtesting
```bash
# Backtest 3 anni (NUOVO SISTEMA)
python scripts/backtest_portfolio.py --years=3 --capital=10000

# Backtest V1 (legacy)
python main.py backtest --years=3 --capital=10000

# Walk-forward validation
python main.py walkforward --years=3

# Stress testing
python main.py stress --capital=10000
```

### Paper Trading
```bash
# Start paper trading
python main.py paper --paper-action=start --capital=10000

# Check posizioni e nuovi segnali
python main.py paper --paper-action=check

# Performance summary
python main.py paper --paper-action=summary

# Export CSV
python main.py paper --paper-action=export
```

---

## 🔥 WORKFLOW OPERATIVO

### Setup (Una Volta)
1. ✅ `pip install -r requirements.txt`
2. ✅ Configura `config/config.yaml` (API key)
3. ✅ `python scripts/download_benchmarks.py`
4. ✅ `python main.py update --force-full`

### Trading (Ogni 3-5 Giorni)
1. 📊 `python scripts/test_portfolio_manager.py`
2. 🔍 Rivedi segnali
3. 💰 Esegui trade su Trade Republic
4. 🛡️ Set stop loss + alerts
5. 📈 Update trailing stops se profit > 5%

### Manutenzione (Settimanale)
```bash
# Update dati
python main.py update

# Check performance (se usi paper trading)
python main.py paper --paper-action=summary
```

---

## ❓ FAQ

### "Quale comando usare per trading?"
→ `python scripts/test_portfolio_manager.py` ✅

### "Come vedo l'interfaccia grafica?"
→ `python run.py` 🖥️

### "Come scarico nuovi dati?"
→ `python main.py update` 📥

### "Come backtest?"
→ `python scripts/backtest_portfolio.py --years=3` 📊

### "Come faccio paper trading?"
→ `python main.py paper --paper-action=start` 📝

---

## 🎯 QUICK REFERENCE

| Obiettivo | Comando |
|-----------|---------|
| **Segnali Trading** | `python scripts/test_portfolio_manager.py` |
| **Dashboard** | `python run.py` |
| **Update Dati** | `python main.py update` |
| **Backtest** | `python scripts/backtest_portfolio.py --years=3` |
| **Paper Trading** | `python main.py paper --paper-action=summary` |
| **Check Regime** | `python scripts/check_spy_regime.py` |

---

## 💡 PROVA SUBITO!

**Test rapido (senza setup)**:
```bash
python scripts/test_portfolio_manager.py
```

Vedi i segnali di oggi in 10 secondi!

---

**Creato**: Febbraio 2026  
**Per**: Trading con €10,000  
**Timeframe**: Swing trading 5-15 giorni
