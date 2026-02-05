# Guida Operativa: Da Segnali DSS a Ordini su Trade Republic

## Panoramica

Questa guida spiega come tradurre i segnali generati dal sistema DSS (in USD) in ordini reali su Trade Republic (in EUR).

---

## Come Funziona Trade Republic per Azioni USA

### Il Meccanismo

Trade Republic non ti connette direttamente a NYSE o NASDAQ. Tutte le azioni USA passano per **LS Exchange** (Lang & Schwarz), una borsa tedesca che quota le azioni americane in EUR.

```
NYSE (New York)          LS Exchange (Amburgo)         Tu
     |                          |                       |
  AAPL $185.00    →    AAPL €170.50 (già convertito)   → Compri in EUR
```

### Cosa Significa per Te

1. **I prezzi sono già in EUR** - Non devi fare conversioni al momento dell'acquisto
2. **Lo spread di cambio è incluso** - TR applica ~0.5% di spread EUR/USD, ma è già nel prezzo
3. **La liquidità dipende dall'orario** - Spread stretti solo quando NYSE è aperto

---

## Conversione Segnali: USD → EUR

### Formula Base

```
Prezzo EUR = Prezzo USD × Tasso di Cambio

Dove il tasso di cambio attuale è circa 0.92 (febbraio 2026)
```

### Tabella di Conversione Rapida

| USD | EUR (×0.92) |
|-----|-------------|
| $50 | €46 |
| $100 | €92 |
| $150 | €138 |
| $175 | €161 |
| $200 | €184 |
| $250 | €230 |
| $300 | €276 |
| $500 | €460 |

### Come Ottenere il Cambio Esatto

1. **Google**: cerca "USD to EUR" per il tasso live
2. **XE.com**: https://www.xe.com/currencyconverter/
3. **Trade Republic**: guarda il prezzo di un'azione che conosci e confronta con Yahoo Finance

---

## Workflow Completo: Dal Segnale all'Ordine

### FASE 1: Lunedì Sera - Ricevi i Segnali

Il sistema DSS genera segnali come questo:

```
═══════════════════════════════════════════════════════
SEGNALE: AAPL (Apple Inc.)
Strategia: momentum_simple
═══════════════════════════════════════════════════════
Entry Price:    $185.50
Stop Loss:      $176.20  (-5.0%)
Target Price:   $202.00  (+8.9%)
Position Size:  8 shares
Risk Amount:    €15.00 (1.5% di €1,000)
═══════════════════════════════════════════════════════
```

### FASE 2: Converti in EUR

Prendi il tasso di cambio attuale (es. 0.92):

```
Entry:  $185.50 × 0.92 = €170.66 → arrotonda a €170.70
Stop:   $176.20 × 0.92 = €162.10 → arrotonda a €162.00
Target: $202.00 × 0.92 = €185.84 → arrotonda a €186.00
```

**Regola di arrotondamento**:
- Entry: arrotonda **per eccesso** (paghi un po' di più, più sicuro che l'ordine venga eseguito)
- Stop: arrotonda **per difetto** (esci un po' prima, più conservativo)
- Target: arrotonda **per eccesso** (incassi un po' di più)

### FASE 3: Martedì 15:25 - Prepara l'Ordine

1. Apri Trade Republic
2. Cerca il titolo (es. "AAPL" o "Apple")
3. Controlla il prezzo attuale mostrato (es. €170.20)
4. Confronta con la tua entry convertita (€170.70)

### FASE 4: Martedì 15:30 - Piazza l'Ordine

**Se il prezzo attuale è SOTTO la tua entry** (es. €170.20 < €170.70):
```
✅ Piazza LIMIT ORDER a €170.70
   L'ordine verrà eseguito appena il prezzo sale a €170.70
   (o subito se il prezzo è già lì)
```

**Se il prezzo attuale è SOPRA la tua entry** (es. €172.00 > €170.70):
```
⚠️ Il titolo è già salito oltre il tuo entry ideale
   
   Opzione A: Piazza limit a €172.50 (accetti entry peggiore)
   Opzione B: SKIP - non entrare, aspetta il prossimo segnale
   
   Consiglio: se il prezzo è >2% sopra l'entry, meglio saltare
```

### FASE 5: Imposta lo Stop Loss

Dopo che l'ordine è stato eseguito:

1. Vai sulla posizione aperta
2. Imposta **Stop Loss** a €162.00
3. Tipo: "Stop Loss" (non "Stop Limit")

**IMPORTANTE**: Su Trade Republic lo stop loss è monitorato durante gli orari di trading di LS Exchange (8:00-22:00). Durante la notte il titolo può scendere sotto lo stop senza che venga eseguito.

### FASE 6: Monitora (Mercoledì-Giovedì)

- Controlla una volta al giorno se lo stop è stato colpito
- Se il prezzo sale significativamente (+6% o più), considera di alzare lo stop manualmente (trailing stop manuale)

### FASE 7: Venerdì - Decisione

Il sistema non chiude automaticamente il venerdì. Tu devi decidere:

- **Se in profitto >3%**: Tieni, alza lo stop a breakeven (prezzo di entry)
- **Se in profitto 0-3%**: Tieni, mantieni lo stop originale
- **Se in perdita**: Lo stop dovrebbe già averti protetto. Se no, valuta se chiudere

---

## Esempio Completo Pratico

### Scenario

```
Capitale: €1,000
Data: Lunedì 10 febbraio 2026
Tasso EUR/USD: 0.92
```

### Segnale Ricevuto

```
NVDA (Nvidia)
Entry: $890.00
Stop: $845.50 (-5%)
Target: $970.00 (+9%)
Shares: 1
Risk: €15 (1.5%)
```

### Conversione

```
Entry:  $890.00 × 0.92 = €818.80 → €819.00
Stop:   $845.50 × 0.92 = €777.86 → €777.00  
Target: $970.00 × 0.92 = €892.40 → €893.00
```

### Martedì 15:30

```
Apro Trade Republic
Cerco "NVDA"
Prezzo attuale: €815.50

€815.50 < €819.00 ✅ OK, posso entrare

Piazzo: LIMIT ORDER ACQUISTO
        Quantità: 1 azione
        Prezzo limite: €819.00
        
Ordine eseguito a €817.30 (sotto il mio limite, meglio!)
```

### Dopo l'Esecuzione

```
Imposto STOP LOSS: €777.00

Riepilogo posizione:
- Acquistato: 1 NVDA a €817.30
- Stop Loss: €777.00
- Target: €893.00
- Rischio: €817.30 - €777.00 = €40.30 per azione
```

### Giovedì

```
NVDA sale a €865.00

Profitto attuale: (€865 - €817.30) / €817.30 = +5.8%

Opzione: alzo stop a €817.30 (breakeven) per proteggere i guadagni
         → Se torna giù, esco a pari invece che in perdita
```

### Venerdì

```
NVDA chiude a €878.00

Profitto: +7.4%, ma sotto il target (€893)
Decisione: TENGO, alzo stop a €850.00 (lock +4%)
           Lascio correre per la prossima settimana
```

---

## Tabella Riassuntiva Ordini

| Tipo Ordine | Quando Usarlo | Come su TR |
|-------------|---------------|------------|
| **Limit Buy** | Entry su segnale | "Acquista" → "Ordine Limite" |
| **Stop Loss** | Protezione perdite | Sulla posizione → "Stop Loss" |
| **Limit Sell** | Presa profitto target | "Vendi" → "Ordine Limite" |

---

## Orari Ottimali

| Orario (CET) | Cosa Fare | Perché |
|--------------|-----------|--------|
| 15:25-15:30 | Preparare ordini | NYSE sta per aprire |
| 15:30-17:30 | **Finestra ideale** | NYSE + XETRA aperti, spread minimi |
| 17:30-22:00 | Ancora OK | Solo NYSE aperto, spread accettabili |
| 22:00-15:30 | **EVITARE** | Spread larghi, poca liquidità |

---

## Checklist Pre-Trade

Prima di ogni ordine, verifica:

- [ ] Sono dopo le 15:30 CET?
- [ ] Ho convertito entry/stop/target in EUR?
- [ ] Il prezzo attuale è entro 2% dall'entry calcolato?
- [ ] Ho abbastanza capitale per la posizione + le altre aperte?
- [ ] Non ho già 3 posizioni aperte? (max slot)
- [ ] Ho impostato lo stop loss subito dopo l'acquisto?

---

## Errori Comuni da Evitare

### 1. Market Order invece di Limit
```
❌ Clicchi "Acquista" e confermi subito
✅ Clicchi "Acquista" → "Ordine Limite" → Inserisci prezzo
```

### 2. Comprare Prima delle 15:30
```
❌ Vedi il segnale lunedì sera e compri martedì alle 9:00
✅ Aspetti martedì 15:30 quando NYSE apre
```

### 3. Dimenticare lo Stop Loss
```
❌ Compri e "vediamo come va"
✅ Imposti SEMPRE lo stop loss entro 5 minuti dall'acquisto
```

### 4. Ignorare il Cambio EUR/USD
```
❌ Il segnale dice $185, metti limit a €185
✅ Converti: $185 × 0.92 = €170.20
```

### 5. Entrare su Gap Up
```
❌ Entry era €170, il titolo apre a €180, compri comunque
✅ Se >2% sopra entry, SKIP il segnale
```

---

## Domande Frequenti

### "Devo convertire ogni volta?"
Sì, ma diventa automatico. Dopo un paio di settimane farai la moltiplicazione ×0.92 a mente.

### "Il cambio EUR/USD cambia ogni giorno?"
Sì, ma di poco (0.1-0.5%). Usa il tasso del giorno in cui piazzi l'ordine.

### "Cosa faccio se l'ordine limite non viene eseguito?"
Se dopo 1-2 ore l'ordine è ancora pendente, cancellalo. Il segnale è "scaduto" - aspetta il prossimo lunedì.

### "Lo stop loss funziona di notte?"
No. LS Exchange chiude alle 22:00. Se il titolo gappa durante la notte, lo stop verrà eseguito all'apertura del giorno dopo, potenzialmente a un prezzo peggiore.

### "Posso usare Take Profit automatico?"
Sì, TR lo supporta. Puoi impostare un ordine "Take Profit" al tuo target (es. €893). Ma il sistema DSS non usa target fissi - usa trailing stop. Quindi è meglio gestire l'uscita manualmente.

---

## Risorse Utili

- **Conversione valuta**: https://www.xe.com/currencyconverter/
- **Prezzi live USA**: https://finance.yahoo.com
- **Calendario mercati**: https://www.tradinghours.com/markets/nyse

---

## Versione

Documento creato: 4 febbraio 2026
Sistema DSS versione: Post-ottimizzazione (PF 1.14-1.39)
