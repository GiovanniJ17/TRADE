# DSS Trading System — Migliorie Quality of Life

> Analisi del codebase attuale con suggerimenti pratici per migliorare l'esperienza d'uso quotidiana.  
> Priorità: impatto immediato sull'utente, basso costo di implementazione.

---

## 1. Dashboard UX — Navigazione e Feedback

### 1.1 Indicatore stato dati nella sidebar

**Problema:** Attualmente non c'è modo rapido di capire se i dati sono aggiornati o stale. L'unico feedback è il timestamp "Last update" che appare solo dopo aver cliccato il bottone.

**Suggerimento:** Aggiungere nella sidebar un badge colorato permanente:
- 🟢 "Dati aggiornati (oggi)" — se `last_update` è di oggi
- 🟡 "Dati di ieri" — se i dati sono del giorno precedente
- 🔴 "Dati vecchi (3+ giorni)" — se i dati sono stale

In più, all'avvio della dashboard, controllare automaticamente la data dell'ultimo record in DuckDB e mostrare il badge senza bisogno di cliccare nulla.

### 1.2 Status del mercato USA visibile in Home

**Problema:** Il modulo `market_hours.py` ha già tutta la logica per `get_market_status()` (aperto, pre-market, chiuso, prossima apertura), ma questa informazione **non viene mai mostrata nella dashboard**.

**Suggerimento:** Nella Home page, aggiungere un widget compatto:
```
🟢 Mercato APERTO — Regular Session (chiude tra 2h 15m)
🟡 Pre-Market — Apertura tra 45 minuti
🔴 Mercato CHIUSO — Weekend. Prossima apertura: Lun 15:30 CET
```

Questo aiuta a capire immediatamente se ha senso aggiornare i dati o generare segnali.

### 1.3 Workflow guidato step-by-step

**Problema:** La Home page ha un lungo blocco markdown con le istruzioni. Un utente che usa il sistema ogni giorno non ha bisogno di rileggere il manuale, ma di sapere: "cosa devo fare adesso?"

**Suggerimento:** Sostituire (o affiancare) il manuale statico con un **checklist dinamica**:

```
📋 Workflow di oggi (Mercoledì 5 Feb)
[✅] Mercato: aperto
[✅] Dati aggiornati: sì (ultimo update 14:32)
[⬜] Segnali generati: no → [Genera Segnali]
[⬜] Posizioni controllate: 2 aperte → [Vai a Posizioni]
```

Ogni step si completa automaticamente in base allo stato reale della sessione.

---

## 2. Gestione Posizioni — Meno click, più contesto

### 2.1 Trailing stop suggerito automaticamente

**Problema:** La pagina "My Positions" mostra il P&L corrente ma non suggerisce quando o come spostare lo stop. L'utente deve calcolare manualmente se conviene spostare lo stop a breakeven o usare il trailing.

**Suggerimento:** Per ogni posizione in profitto, mostrare un suggerimento inline:
```
📈 AAPL +4.7% — Suggerimento: sposta stop a breakeven ($182.50)
📈 NVDA +12.3% — Suggerimento: trailing stop a $875.00 (6% sotto il max)
```

La logica dei trailing stop (6% / 3.5% / 1.5%) è già documentata nella roadmap. Basta calcolarla e mostrarla.

### 2.2 Conferma chiusura con recap P&L

**Problema:** Quando si chiude una posizione, il form chiede l'exit price ma non mostra un riepilogo complessivo di come è andato il trade (durata, R-multiple, confronto con target).

**Suggerimento:** Prima di confermare la chiusura, mostrare:
```
📊 Riepilogo Trade NVDA
   Durata: 12 giorni
   Entry: $845.00 → Exit: $920.00
   P&L: +$375.00 (+8.9%)
   R-Multiple: +1.8R (target era 2.0R)
   Commissioni stimate: €2.00
   Netto in EUR: ~€343.00
```

### 2.3 Quick-close da posizione aperta

**Problema:** Per chiudere una posizione servono 3 click: "Update Position" → selezionare "Close Position" → compilare form. Per i casi semplici (stop hit, target raggiunto) è troppo.

**Suggerimento:** Aggiungere due bottoni rapidi direttamente sulla card della posizione:
- "🛑 Stoppato" — pre-compila con stop loss come exit price
- "🎯 Target raggiunto" — pre-compila con target price come exit price

---

## 3. Segnali — Leggibilità e Contesto

### 3.1 Mini-chart per ogni segnale

**Problema:** I segnali mostrano solo numeri (entry, stop, target) ma non c'è contesto visivo. Un piccolo sparkline o candlestick chart degli ultimi 30 giorni aiuterebbe enormemente a capire il setup.

**Suggerimento:** Usare Plotly (già importato) per generare un mini-chart inline per ogni segnale, con entry/stop/target segnati come linee orizzontali. Non servono chart interattivi complessi: un grafico lineare di 200px di altezza basta.

### 3.2 Confronto con segnali precedenti

**Problema:** Non c'è modo di sapere "questo ticker era già nei segnali la settimana scorsa?" o "il sistema ha già generato un segnale su AAPL che non ho eseguito?"

**Suggerimento:** Nella signal card, aggiungere una nota se il ticker ha avuto segnali recenti:
```
ℹ️ AAPL: segnale anche 3 giorni fa (non eseguito)
⚠️ AMD: posizione già aperta — skip
```

Questo richiede solo un check sulla tabella `signal_history` e `trading_journal`.

### 3.3 Mostrare il "perché" del segnale

**Problema:** Il sistema mostra la strategia usata (Momentum, Mean Reversion, Breakout) ma non spiega i dati sottostanti. Perché proprio questo ticker?

**Suggerimento:** Aggiungere un expander "📖 Dettagli analisi" per ogni segnale:
```
📖 Dettagli — NVDA (Momentum)
   SMA200: $780 (prezzo sopra ✅)
   RSI(14): 58 (neutro, non ipercomprato ✅)
   Volume: 1.3x media (confermato ✅)
   NATR: 2.1% (volatilità moderata ✅)
   Settore: Semiconductors (esposizione attuale: 0%)
```

I dati ci sono già nel calcolo degli indicatori, vanno solo esposti.

---

## 4. Notifiche e Automazione Leggera

### 4.1 Promemoria "dati non aggiornati"

**Problema:** Se l'utente apre la dashboard di lunedì ma dimentica di aggiornare i dati, genera segnali su dati di venerdì senza saperlo.

**Suggerimento:** Se i dati sono più vecchi di 1 giorno di trading:
```
⚠️ I dati di mercato sono di venerdì 31 Gen.
    Aggiorna prima di generare segnali → [Aggiorna Dati]
```

Bloccare opzionalmente la generazione segnali su dati stale (con override manuale).

### 4.2 Riepilogo giornaliero Telegram migliorato

**Problema:** Il bot Telegram esiste ma manda solo alert su nuovi segnali. Manca un riepilogo compatto dello stato del portfolio.

**Suggerimento:** Aggiungere un messaggio daily (es. alle 22:00 CET):
```
📊 DSS Daily Report — 5 Feb 2026
   Portfolio: 2 posizioni aperte
   P&L oggi: +€45 (+1.2%)
   Regime: TRENDING 🟢
   Prossima azione: monitoraggio (nessun segnale nuovo)
```

### 4.3 Auto-update dati con scheduler

**Problema:** L'aggiornamento dati è completamente manuale. L'utente deve ricordarsi di cliccare il bottone.

**Suggerimento:** Aggiungere nelle Settings un'opzione "Auto-update all'avvio":
- Se attivato, all'apertura della dashboard i dati vengono aggiornati automaticamente (con progress bar)
- Alternativa leggera: un cron job locale (`crontab` su Mac/Linux) che esegue `python main.py update` alle 22:00 CET

---

## 5. Settings e Configurazione

### 5.1 Conferma visiva dopo ogni modifica

**Problema:** Dopo aver cambiato i settings, appare "Regenerate signals to apply new settings" ma non c'è un bottone diretto per farlo. L'utente deve scrollare su nella sidebar.

**Suggerimento:** Aggiungere un bottone inline "🔄 Rigenera segnali con nuovi parametri" direttamente sotto il messaggio di conferma nelle Settings.

### 5.2 Anteprima impatto delle modifiche

**Problema:** Cambiare capital o risk per trade non mostra l'impatto prima di applicare.

**Suggerimento:** Mostrare un confronto before/after:
```
💰 Modifica capitale: €1,500 → €3,000
   Prima: max €450/posizione (3 slot)
   Dopo: max €900/posizione (3 slot)
   Risk per trade: €20 = 0.67% del capitale (era 1.33%)
```

### 5.3 Export/Import configurazione

**Problema:** Se l'utente vuole fare un backup o testare configurazioni diverse, non c'è modo di salvare/ripristinare i settings.

**Suggerimento:** Due bottoni nelle Settings:
- "📥 Esporta configurazione" → genera un JSON con tutti i parametri correnti
- "📤 Importa configurazione" → carica un JSON e applica i parametri

---

## 6. Trade History — Analisi più utile

### 6.1 Equity curve

**Problema:** La pagina Trade History mostra una tabella di trade chiusi ma nessun grafico. Vedere l'andamento del capitale nel tempo è fondamentale per capire se il sistema funziona.

**Suggerimento:** Aggiungere un grafico Plotly dell'equity curve basata sui trade chiusi. Linea del capitale nel tempo con drawdown evidenziato in rosso.

### 6.2 Statistiche per strategia

**Problema:** Le statistiche sono aggregate. Non si può sapere se Momentum performa meglio di Mean Reversion.

**Suggerimento:** Aggiungere un breakdown:
```
📊 Performance per Strategia
   Momentum:      8 trade, WR 62%, PF 1.45
   Mean Reversion: 5 trade, WR 60%, PF 1.12
   Breakout:       3 trade, WR 33%, PF 0.80
```

Richiede di salvare la strategia usata in `trading_journal` (attualmente non viene tracciata).

### 6.3 Calendario trade

**Problema:** La tabella non dà una visione d'insieme temporale.

**Suggerimento:** Un mini-calendario (stile GitHub contribution graph) che mostra i giorni con trade aperti/chiusi/in profit/in loss. Aiuta a identificare pattern (es. "perdo sempre il lunedì").

---

## 7. Robustezza Tecnica

### 7.1 Gestione errori di rete graceful

**Problema:** Se Polygon.io è down o la rete è assente, l'update fallisce con un errore tecnico. L'utente vede uno stacktrace.

**Suggerimento:** Catturare gli errori comuni e mostrare messaggi umani:
- Timeout → "Polygon.io non risponde. Riprova tra qualche minuto."
- 429 → "Limite API raggiunto. Attendi 60 secondi."
- Network error → "Nessuna connessione internet."

Con un bottone "🔄 Riprova" automatico.

### 7.2 Pulizia log automatica

**Problema:** I log crescono senza limite visibile. I file nella cartella `logs/` sono già da 2-3 MB/giorno.

**Suggerimento:** La retention a 30 giorni è già configurata in loguru, ma aggiungere nelle Settings una sezione "Manutenzione" con:
- Spazio disco usato da log e database
- Bottone "Pulisci log vecchi"
- Dimensione del database DuckDB (attualmente 86 MB)

### 7.3 Validazione dati prima della generazione segnali

**Problema:** Se il database ha dati corrotti o incompleti per un ticker, la generazione segnali potrebbe fallire silenziosamente o dare risultati errati.

**Suggerimento:** Prima di generare segnali, fare un quick health check:
- Verifica che SPY (benchmark) abbia dati recenti
- Conta i ticker con dati recenti vs totale watchlist
- Segnala ticker con gap anomali nei dati

---

## 8. Piccoli tocchi che fanno la differenza

### 8.1 Dark mode

Streamlit supporta nativamente il tema dark. Aggiungere un `.streamlit/config.toml`:
```toml
[theme]
primaryColor = "#4CAF50"
backgroundColor = "#0E1117"
secondaryBackgroundColor = "#262730"
textColor = "#FAFAFA"
```

### 8.2 Favicon e titolo dinamico

Il titolo della tab è statico. Mostrare il P&L nel titolo:
```
📈 DSS +€45 | 2 posizioni
```

Così anche con la tab in background sai come va.

### 8.3 Keyboard shortcuts

Streamlit non supporta shortcut nativi, ma si possono aggiungere con un componente JS custom:
- `R` → Rigenera segnali
- `U` → Aggiorna dati
- `1-6` → Navigazione pagine

### 8.4 Tempo CET accanto a tutti i timestamp

**Problema:** Alcuni timestamp mostrano l'ora ET (mercato US), altri l'ora locale. Non c'è consistenza.

**Suggerimento:** Mostrare sempre entrambi: `14:32 CET (8:32 ET)` oppure scegliere una convenzione unica e mantenerla.

---

## Priorità consigliata di implementazione

| # | Miglioria | Sforzo | Impatto | Priorità |
|---|-----------|--------|---------|----------|
| 1 | Status mercato in Home (1.2) | 30 min | Alto | ⭐⭐⭐ |
| 2 | Badge dati aggiornati (1.1) | 30 min | Alto | ⭐⭐⭐ |
| 3 | Promemoria dati stale (4.1) | 20 min | Alto | ⭐⭐⭐ |
| 4 | Trailing stop suggerito (2.1) | 1-2 ore | Alto | ⭐⭐⭐ |
| 5 | Quick-close posizione (2.3) | 1 ora | Medio | ⭐⭐ |
| 6 | Dettagli segnale (3.3) | 2 ore | Medio | ⭐⭐ |
| 7 | Equity curve (6.1) | 1-2 ore | Medio | ⭐⭐ |
| 8 | Workflow checklist (1.3) | 2-3 ore | Alto | ⭐⭐ |
| 9 | Mini-chart segnali (3.1) | 2-3 ore | Medio | ⭐⭐ |
| 10 | Recap chiusura trade (2.2) | 1 ora | Medio | ⭐⭐ |
| 11 | Stats per strategia (6.2) | 2 ore | Medio | ⭐ |
| 12 | Auto-update avvio (4.3) | 1 ora | Medio | ⭐ |
| 13 | Export/import config (5.3) | 1-2 ore | Basso | ⭐ |
| 14 | Dark mode (8.1) | 10 min | Basso | ⭐ |

*Le prime 4 migliorie richiedono ~3 ore totali e trasformano l'esperienza d'uso quotidiana.*
