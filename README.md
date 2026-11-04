# Segnali Nasdaq

Scanner sul Nasdaq-100 con **due strategie indipendenti**, notifiche su Android e Windows e dashboard
con il grafico delle performance. Costi eToro e tasse italiane (26%) sono inclusi.

| Strategia | Orizzonte | Titolo notifica |
|-----------|-----------|-----------------|
| **Breakout** | fino a ~4 settimane (20 giorni di borsa) | `[BREAKOUT] COMPRA XXX` |
| **Rimbalzo** | massimo 1 settimana (5 giorni di borsa) | `[RIMBALZO] COMPRA XXX` |

Le due strategie hanno parametri, segnali e statistiche separati. Nella dashboard trovi i pulsanti
**Tutte / Breakout / Rimbalzo**. Un titolo già aperto (o in attesa) in una strategia non viene
riproposto dall'altra.

## 1. Notifiche (2 minuti)
1. Installa l'app **ntfy** su Android (Play Store) e, su Windows, apri https://ntfy.sh/app oppure installa l'app desktop.
2. Iscriviti al topic scritto in `config.json` (`ntfy_topic`). **Cambialo con una stringa tua e lunga**: chiunque la conosca può leggere le notifiche.

## 2. Funzionamento automatico (consigliato, gratis)
1. Crea un repository su GitHub (con account gratuito deve essere pubblico per usare Pages) e carica questa cartella.
   Poi Settings -> Secrets and variables -> Actions -> New secret: nome `NTFY_TOPIC`, valore il tuo topic segreto (così non resta visibile nel repo).
2. Settings -> Pages -> sorgente: branch `main`, cartella `/docs`.
3. Actions -> "Scansione Nasdaq" -> Run workflow per il primo avvio.
   Poi gira da solo ogni sera dopo la chiusura di Wall Street.
4. Apri l'indirizzo di Pages dal telefono -> menu del browser -> "Installa app".
   Su Windows: Edge/Chrome -> "Installa".

## 3. Funzionamento solo in locale su Windows
Installa Python 3.9+ e fai doppio clic su `avvia_windows.bat`.
Per l'esecuzione automatica usa Utilità di pianificazione alle 22:30 (lun-ven).
Le notifiche arrivano comunque anche sul telefono tramite ntfy.

## Come leggere un alert
Ogni alert di acquisto indica una **fascia di apertura** ("compra domani SOLO se apre tra X e Y $").
È la conferma del giorno dopo: se il titolo apre fuori fascia il segnale viene annullato
(la dashboard lo mostra in "Annullati all'apertura") e arriva una notifica `ANNULLATO`.
Dopo l'acquisto imposta su eToro stop e obiettivo usando le distanze indicate nell'alert (sono in dollari rispetto al tuo prezzo di acquisto reale).

## Strategia BREAKOUT
Rimane la rottura del massimo a 20 giorni in un trend rialzista, ma con filtri contro i falsi breakout:

- **Trend**: QQQ sopra la media a 200 giorni; titolo con prezzo > SMA50 > SMA200 e SMA50 in salita.
- **Rottura vera**: la *chiusura* deve stare oltre il massimo dei 20 giorni precedenti (prima bastava restare entro l'1,5% sotto), ma non oltre 1,5 ATR sopra: niente inseguimento.
- **Chiusura forte**: candela rialzista che chiude nel 30% alto del suo range (le lunghe ombre superiori sono il segno tipico del rifiuto).
- **Volumi** almeno 1,4 volte la media a 20 giorni (prima 1,2).
- **RSI** tra 50 e 70 (RSI di Wilder, come su eToro/TradingView).
- **Niente candele climax** (range oltre 2,5 ATR) né gap da notizie oltre 1,5 ATR.
- **Base ordinata**: i 20 giorni precedenti non devono essere troppo ampi (max 7 ATR).
- **Poca resistenza sopra**: prezzo entro il 10% dal massimo annuale.
- **Forza relativa**: il titolo deve battere QQQ negli ultimi 60 giorni.
- **Conferma all'apertura**: se il giorno dopo apre sotto il livello rotto (-0,1 ATR) è un falso breakout e il segnale cade; se apre oltre +1 ATR dalla chiusura non lo si insegue.
- Obiettivo +4 ATR, stop -2 ATR, chiusura massima dopo 20 giorni di borsa.

## Strategia RIMBALZO
Cerca un ipervenduto che sta tornando a salire, dentro un trend di fondo rialzista.

Condizioni obbligatorie:
- QQQ sopra la media a 200 giorni e titolo sopra la propria SMA200.
- **RSI(14)** sceso a 40 o meno nelle ultime 5 sedute, oggi in risalita e non oltre 55.
- **MACD(12,26,9)**: la linea MACD incrocia **dal basso verso l'alto** la linea segnale (oggi; con `macd_cross_days: 2` anche ieri).
- Prezzo almeno 0,5 ATR sotto la media a 20 giorni (spazio per risalire) e calo dal massimo a 20 giorni non oltre il 20% (evita i "coltelli che cadono").

Conferme aggiuntive (ne servono almeno 3 su 5):
1. **Bande di Bollinger (20, 2)**: tocco della banda inferiore nelle ultime 3 sedute e rientro.
2. **Stocastico (14,3,3)**: incrocio rialzista %K su %D partendo da ipervenduto (<= 30).
3. **Candela di rimbalzo**: chiude verde e nella parte alta del range.
4. **Volumi** pari o sopra la media.
5. **MACD che incrocia sotto lo zero** (pullback profondo, non un semplice rallentamento).

Gestione: obiettivo +2 ATR, stop -1,5 ATR, chiusura massima dopo 5 giorni di borsa.
Conferma all'apertura: se apre oltre 0,5 ATR sotto la chiusura il rimbalzo è fallito; oltre +1 ATR è già avvenuto. In entrambi i casi il segnale cade.

## Configurazione
`config.json` ha una sezione per strategia (`breakout`, `rimbalzo`) e i parametri comuni (importo, tasse, cambio).
Ogni valore non scritto usa il default in `scanner.py`. Si può disattivare una strategia con `"enabled": false`.
Se una sera non arriva nessun segnale, il log (Actions -> Scansione Nasdaq) indica quali filtri hanno escluso più titoli,
così sai quale soglia allentare.

## Note fiscali
Conversione EUR/USD: 0,5% per lato (da verificare sul tuo conto). Con eToro sei in regime dichiarativo:
il 26% va indicato nella dichiarazione dei redditi; le minusvalenze sono compensabili per 4 anni.
Il calcolo è una stima e non sostituisce un commercialista.
Nel rimbalzo (posizioni brevi) cambio e commissioni pesano di più sul rendimento: per questo c'è un profitto netto minimo (`min_net_profit_eur`).

Strumento statistico, non consulenza finanziaria. Nessun profitto è garantito.
I filtri sono regole classiche dell'analisi tecnica, non ottimizzate su dati storici.
