# DSS Trading System — Roadmap Migliorie Future

> **Versione:** 1.0 | **Data:** Febbraio 2026  
> **Stato attuale:** PF 1.19 | WR 60% | Return +8.2% (1Y backtest)  
> **Configurazione:** MAX_HOLD 8 settimane | Trailing 6%/3.5%/1.5% | Risk 1.5% equity compound | ATR×2.0 stop

---

## Fase 1 — Validazione Live (Mesi 0–6)

**Obiettivo:** Confermare che il backtest predice la realtà.

**Costo:** €0 | **Tempo:** 15-20 min/giorno (già previsto)

### 1.1 Operare il sistema senza modifiche

Il dato più prezioso che puoi ottenere nei primi 6 mesi è la risposta alla domanda: "il backtest è affidabile?". Ogni modifica fatta prima di avere questa risposta è prematura.

**Azioni:**
- Seguire rigorosamente la Guida Operativa Trade Republic
- Registrare ogni trade in un journal: data entry, prezzo entry, data exit, prezzo exit, motivo exit (stop/trailing/max_hold), P&L
- NON modificare parametri, NON aggiungere strategie, NON cambiare nulla

### 1.2 Confronto Live vs Backtest

Dopo 3 e 6 mesi, confrontare:

| Metrica | Backtest | Live 3M | Live 6M |
|---------|----------|---------|---------|
| Win Rate | 60% | ? | ? |
| Profit Factor | 1.19 | ? | ? |
| Avg R per trade | +0.08 | ? | ? |
| Max Drawdown | 9-10% | ? | ? |

**Interpretazione:**
- PF live > 1.0 → sistema profittevole, procedere con Fase 2
- PF live 0.85-1.0 → edge marginale, analizzare se slippage/timing sono il problema
- PF live < 0.85 → edge non confermato, fermarsi e analizzare prima di continuare

### 1.3 Documentare le discrepanze

Ogni differenza tra backtest e live va documentata:
- Slippage reale vs stimato (0.2%)
- Ordini non eseguiti (gap, liquidità insufficiente)
- Errori operativi (ordine sbagliato, timing errato)
- Differenze di prezzo LS Exchange vs dati Polygon.io

---

## Fase 2 — Ottimizzazione Robusta (Mesi 6–12)

**Obiettivo:** Rendere il sistema più robusto senza cambiarne la natura.

**Costo:** €0 | **Tempo:** 10-20 ore totali di sviluppo

### 2.1 Walk-Forward Validation

Invece di ottimizzare su tutto lo storico (rischio overfitting), implementare un processo rolling:

1. Ottimizzare parametri su 12 mesi di dati (in-sample)
2. Testare sui 3 mesi successivi (out-of-sample) senza modifiche
3. Spostare la finestra avanti di 3 mesi
4. Ripetere

**Se i parametri reggono su tutte le finestre:** l'edge è strutturale e robusto.  
**Se funzionano solo su certi periodi:** c'è overfitting, serve semplificazione.

**Implementazione:** Modificare `backtest_portfolio.py` per accettare date range e iterare automaticamente.

### 2.2 Regime Filter

Aggiungere un filtro che riduce l'esposizione in condizioni di mercato sfavorevoli:

**Indicatori candidati:**
- **S&P 500 vs SMA 200:** se sotto → massimo 2 slot invece di 3
- **VIX > 30:** ridurre a 1 slot o non tradare
- **Breadth indicator:** % titoli S&P 500 sopra SMA 50, se < 40% → ridurre esposizione

**Logica:**
```
se mercato_favorevole:
    max_slot = 3  (come ora)
se mercato_neutro:
    max_slot = 2
se mercato_sfavorevole:
    max_slot = 1 oppure 0
```

**Vantaggio atteso:** ridurre il Max Drawdown (ora 9-18%) senza sacrificare troppo rendimento. I drawdown più grandi avvengono quasi sempre quando il mercato complessivo scende.

### 2.3 Migliorare il Scoring/Ranking

Problema strutturale #1 identificato nella code review: il sistema di scoring a 100 punti in `dss/intelligence/scoring.py` viene ignorato dal portfolio manager.

**Azione:** Collegare il ranking effettivo al composite score. Questo richiede:
1. Verificare che lo scoring assegni punteggi sensati ai candidati
2. Modificare `portfolio_manager.py` per ordinare i candidati per score composito
3. Backtestare per verificare se migliora la selezione

**Rischio:** basso — è codice già scritto, solo da integrare.

---

## Fase 3 — Automazione (Mesi 12–18)

**Obiettivo:** Eliminare l'esecuzione manuale e l'errore umano.

**Costo:** €30-50/mese | **Tempo:** 30-50 ore di sviluppo iniziale

### 3.1 Migrazione a Interactive Brokers

Trade Republic è ottimo per iniziare ma non ha API per trading automatico. Interactive Brokers (IB) offre:

| Feature | Trade Republic | Interactive Brokers |
|---------|---------------|-------------------|
| API trading | ❌ | ✅ TWS API / ib_insync |
| Commissioni US | €1/ordine | ~$0.005/share (~$1-2/trade) |
| Accesso diretto NYSE/NASDAQ | ❌ (via LS Exchange) | ✅ |
| Tipi ordine avanzati | Limit, Stop | Limit, Stop, Trailing, Bracket, OCA |
| Slippage stimato | 0.10-0.50% | 0.02-0.10% |
| Costo mensile | €0 | ~€10/mese (inattività, azzerabile con commissioni) |

**Impatto sullo slippage:** accesso diretto a NYSE/NASDAQ elimina il markup LS Exchange e la conversione EUR/USD implicita. Lo slippage potrebbe dimezzarsi, recuperando €1-3 per trade.

**Nota fiscale:** IB non è sostituto d'imposta in Italia → regime dichiarativo, serve commercialista per la dichiarazione. Costo aggiuntivo ~€200-400/anno. Valutare se il risparmio su slippage compensa.

### 3.2 VPS (Virtual Private Server)

Un server cloud che esegue il sistema 24/7:

- **Provider consigliati:** Hetzner (€5-10/mese), DigitalOcean (€6-12/mese), AWS Lightsail (€5-10/mese)
- **Requisiti:** Ubuntu, 2GB RAM, Python 3.10+, connessione stabile
- **Setup:** cron job che esegue il lunedì sera (analisi), martedì mattina (ordini), mercoledì-giovedì (monitoraggio stop), venerdì (exit rules)

**Vantaggio:** il sistema opera anche quando sei in vacanza, malato, o semplicemente occupato. Zero dipendenza dalla tua disponibilità.

### 3.3 Sistema di Notifiche

Anche con automazione completa, vuoi essere informato:

- **Telegram Bot** (gratuito): notifiche push per ogni trade aperto/chiuso, alert su drawdown
- **Email giornaliera:** riepilogo posizioni, P&L, segnali per il giorno dopo
- **Alert critici:** se il drawdown supera una soglia (es. -12%), notifica immediata

---

## Fase 4 — Espansione (Mesi 18+)

**Obiettivo:** Aumentare rendimento e diversificazione.

**Costo:** €100-300/mese | **Tempo:** investimento continuo

### 4.1 Espansione Universo di Titoli

**Mercati aggiuntivi:**
- **Europa (DAX, FTSE 100, CAC 40, AEX):** più candidati = migliore selezione. Stessi principi del sistema attuale, diversi fusi orari
- **ETF settoriali US:** XLK (tech), XLF (financial), XLE (energy) — per catturare rotazioni settoriali
- **Large-cap internazionali:** titoli quotati su più borse con buona liquidità

**Implementazione:** aggiungere nuovi ticker all'universo, verificare che i dati siano disponibili su Polygon.io (o provider alternativo), adattare gli orari di esecuzione.

### 4.2 Strategie Aggiuntive Non Correlate

L'idea chiave: ogni strategia indipendente con edge positivo migliora lo Sharpe ratio complessivo, anche se individualmente mediocre.

**Candidati:**

| Strategia | Logica | Correlazione con DSS attuale |
|-----------|--------|-------------------------------|
| Earnings Momentum | Long dopo earning surprise positiva > X% | Bassa — event-driven vs trend |
| Mean Reversion settimanale | Short-term reversal su RSI estremi | Bassa — contrarian vs momentum |
| Stagionalità | Pattern ricorrenti (es. "Sell in May", Santa Rally) | Molto bassa — calendar-based |
| Pairs Trading | Long/short su coppie correlate (es. GOOG/META) | Quasi zero — market-neutral |
| Breakout su volumi | Entry su rottura di range con volume anomalo | Media — simile ma diverso trigger |

**Regola:** ogni nuova strategia deve essere backtestata indipendentemente con walk-forward validation prima dell'integrazione.

### 4.3 Dati Alternativi

Provider di dati più ricchi per strategie più sofisticate:

| Tipo dato | Fonte | Costo stimato | Uso |
|-----------|-------|---------------|-----|
| Fondamentali (EPS, revenue, margini) | Tiingo / Quandl | €30-50/mese | Filtro qualità azienda |
| Short Interest | FINRA / Ortex | €50-100/mese | Identificare short squeeze |
| Insider Trading | SEC EDGAR (gratuito) | €0 | Segnale di confidenza management |
| Flussi istituzionali | WhaleWisdom | €30/mese | Seguire smart money |
| Sentiment (news/social) | StockTwits API / NewsAPI | €0-50/mese | Filtro sentiment estremo |

### 4.4 Machine Learning per Ranking

Con 12-18 mesi di dati storici (segnali generati + risultati reali), è possibile allenare un modello che impara quali features predicono i trade migliori.

**Approccio consigliato:**
- NON usare ML per generare segnali (troppo rischio overfitting)
- Usare ML per FILTRARE e PRIORITIZZARE i segnali esistenti
- Features: score composito, NATR, volume relativo, distanza da SMA, settore, regime di mercato
- Target: trade che chiude in profitto vs perdita
- Modello: Random Forest o Gradient Boosting (interpretabili, robusti)
- Validazione: rigorosamente out-of-sample, walk-forward

**Rischio:** alto se fatto male (overfitting), moderato se fatto con disciplina statistica.

---

## Riepilogo Costi e Impatto Atteso

| Fase | Periodo | Costo/mese | Impatto atteso |
|------|---------|------------|----------------|
| 1 — Validazione | 0-6 mesi | €0 | Conferma edge (fondamentale) |
| 2 — Ottimizzazione | 6-12 mesi | €0 | Riduzione DD, miglior selezione |
| 3 — Automazione | 12-18 mesi | €30-50 | Zero errori umani, meno slippage |
| 4 — Espansione | 18+ mesi | €100-300 | Più strategie, Sharpe migliore |

---

## Principi Guida

1. **Non ottimizzare prematuramente.** Ogni modifica deve essere giustificata dai dati, non dall'intuizione.

2. **I dati reali battono sempre la teoria.** Se il live trading dice qualcosa di diverso dal backtest, credi al live.

3. **Semplicità > Complessità.** Un sistema semplice che capisci bene batte un sistema complesso che non capisci.

4. **Il compound fa il lavoro pesante.** Con PF 1.19 e reinvestimento, il tempo è il tuo alleato più forte. Non serve cercare rendimenti spettacolari.

5. **La disciplina è il vero edge.** Il mercato è pieno di sistemi che funzionano sulla carta. La differenza la fa chi li esegue con costanza, mese dopo mese, anche quando il drawdown fa male.

---

*Documento generato come riferimento strategico. Da aggiornare ogni 6 mesi con i risultati reali del live trading.*
