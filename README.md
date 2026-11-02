# Segnali Nasdaq

Scanner swing (operazioni di qualche settimana) sul Nasdaq-100 con notifiche su Android e Windows
e dashboard con il grafico delle performance. Costi eToro e tasse italiane (26%) sono inclusi.

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

## Regole del segnale
- Il Nasdaq (QQQ) deve essere sopra la media a 200 giorni.
- Titolo con prezzo > media 50 > media 200.
- Prezzo a ridosso del massimo a 20 giorni (breakout) con volumi >= 1,2 volte la media.
- RSI tra 50 e 70.
- Obiettivo = +4 ATR, stop = -2 ATR, chiusura massima dopo 20 giorni di borsa (circa 4 settimane).
- Si acquista il giorno dopo all'apertura; l'esito viene registrato in `docs/data.json`.

Parametri modificabili in `config.json` (importo per operazione, costi, ATR, ecc.).

## Note fiscali
Conversione EUR/USD: 0,5% per lato (da verificare sul tuo conto). Con eToro sei in regime dichiarativo:
il 26% va indicato nella dichiarazione dei redditi; le minusvalenze sono compensabili per 4 anni.
Il calcolo è una stima e non sostituisce un commercialista.

Strumento statistico, non consulenza finanziaria. Nessun profitto è garantito.
