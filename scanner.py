#!/usr/bin/env python3
"""Scanner di segnali swing (settimane) sul Nasdaq-100.

- Scarica i dati giornalieri da Yahoo Finance (nessuna chiave API).
- Cerca titoli in trend rialzista con breakout confermato dai volumi.
- Stima il profitto NETTO (costi eToro + tasse italiane 26%).
- Invia notifiche tramite ntfy.sh (Android e Windows).
- Registra ogni segnale e ne verifica l'esito: i dati alimentano il grafico.

Solo libreria standard: serve soltanto Python 3.9+.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")
DATA_FILE = os.path.join(BASE, "docs", "data.json")

NASDAQ_100 = (
    "AAPL MSFT NVDA AMZN META GOOGL GOOG AVGO TSLA COST NFLX TMUS ASML CSCO AZN "
    "LIN PEP ADBE AMD TXN QCOM ISRG INTU AMGN BKNG AMAT HON CMCSA PDD ARM VRTX "
    "PANW ADP SBUX GILD MU ADI LRCX MELI INTC KLAC CRWD CEG REGN SNPS CDNS MDLZ "
    "PYPL MAR CTAS ORLY ABNB MRVL CSX FTNT WDAY DASH ADSK ROP NXPI PCAR CPRT "
    "MNST AEP PAYX FANG CHTR KDP TTD ROST FAST ODFL KHC EA VRSK CTSH EXC LULU "
    "GEHC DDOG XEL TEAM IDXX CCEP BKR ON ANSS CSGP MCHP CDW GFS ZS DXCM BIIB "
    "TTWO MDB WBD ILMN"
).split()


# ----------------------------------------------------------------- utilità
def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    if os.environ.get("NTFY_TOPIC"):  # su GitHub il topic sta nei Secrets, non nel repo
        cfg["ntfy_topic"] = os.environ["NTFY_TOPIC"]
    return cfg


def load_state():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"updated": None, "pending": [], "open": [], "closed": []}


def save_state(state):
    state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def fetch(symbol, rng="1y"):
    """Ritorna lista di barre giornaliere [{d,o,h,l,c,v}] o None."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range={rng}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.load(r)["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        bars = []
        for i, ts in enumerate(res["timestamp"]):
            o, h, l, c, v = (q["open"][i], q["high"][i], q["low"][i],
                             q["close"][i], q["volume"][i])
            if None in (o, h, l, c, v):
                continue
            bars.append({"d": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"),
                         "o": o, "h": h, "l": l, "c": c, "v": v})
        return bars
    except Exception as e:  # rete assente, simbolo errato, ecc.
        print(f"  ! {symbol}: {e}", file=sys.stderr)
        return None


def sma(vals, n):
    return sum(vals[-n:]) / n


def rsi(closes, n=14):
    gains = losses = 0.0
    for i in range(-n, 0):
        diff = closes[i] - closes[i - 1]
        gains += max(diff, 0)
        losses += max(-diff, 0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


def atr(bars, n=14):
    trs = []
    for i in range(-n, 0):
        b, prev = bars[i], bars[i - 1]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - prev["c"]), abs(b["l"] - prev["c"])))
    return sum(trs) / n


# ------------------------------------------------------------ costi e tasse
def net_result(entry, exit_, cfg):
    """Risultato netto in EUR su una posizione di cfg['position_eur'].

    Costi: conversione EUR/USD eToro (fx_fee_per_side) all'ingresso e all'uscita.
    Tasse: 26% sulla plusvalenza. In caso di perdita non si paga nulla
    (la minusvalenza resta compensabile con altre plusvalenze per 4 anni).
    """
    pos = cfg["position_eur"]
    ret = exit_ / entry - 1
    gross = pos * ret
    fees = pos * cfg["fx_fee_per_side"] + pos * (1 + ret) * cfg["fx_fee_per_side"]
    pre_tax = gross - fees
    tax = max(pre_tax, 0) * cfg["tax_rate"]
    return {"gross": round(gross, 2), "fees": round(fees, 2),
            "tax": round(tax, 2), "net": round(pre_tax - tax, 2)}


# ------------------------------------------------------------- segnali
def analyze(symbol, bars, cfg):
    """Ritorna un dict segnale oppure None."""
    if not bars or len(bars) < 210:
        return None
    closes = [b["c"] for b in bars]
    vols = [b["v"] for b in bars]
    last = bars[-1]
    c = last["c"]
    s50, s200 = sma(closes, 50), sma(closes, 200)
    r = rsi(closes)
    high20 = max(b["h"] for b in bars[-21:-1])
    vol_ratio = last["v"] / sma(vols[:-1], 20)
    a = atr(bars)

    trend = c > s50 > s200
    breakout = c >= 0.985 * high20
    momentum = 50 <= r <= 70
    volume = vol_ratio >= 1.2
    if not (trend and breakout and momentum and volume):
        return None

    target = c + cfg["target_atr"] * a
    stop = c - cfg["stop_atr"] * a
    est = net_result(c, target, cfg)
    loss = net_result(c, stop, cfg)
    if est["net"] < cfg["min_net_profit_eur"]:
        return None
    score = vol_ratio + (c / s50 - 1) * 10 + (70 - abs(r - 60)) / 20
    return {"symbol": symbol, "signal_date": last["d"], "ref_price": round(c, 2),
            "atr": round(a, 4), "rsi": round(r, 1), "vol_ratio": round(vol_ratio, 2),
            "target": round(target, 2), "stop": round(stop, 2),
            "est_profit_net": est["net"], "est_loss_net": loss["net"],
            "score": round(score, 2)}


def market_ok():
    bars = fetch("QQQ")
    if not bars or len(bars) < 200:
        return False
    closes = [b["c"] for b in bars]
    return closes[-1] > sma(closes, 200)


# ------------------------------------------------------ tracciamento esiti
def activate_pending(state, data, cfg):
    """Il segnale diventa operazione alla prima barra successiva (ingresso = apertura)."""
    still = []
    for sig in state["pending"]:
        bars = data.get(sig["symbol"]) or []
        nxt = next((b for b in bars if b["d"] > sig["signal_date"]), None)
        if not nxt:
            still.append(sig)
            continue
        entry = nxt["o"]
        sig.update(entry_date=nxt["d"], entry=round(entry, 2),
                   stop=round(entry - cfg["stop_atr"] * sig["atr"], 2),
                   target=round(entry + cfg["target_atr"] * sig["atr"], 2))
        state["open"].append(sig)
    state["pending"] = still


def update_open(state, data, cfg):
    """Chiude le operazioni che hanno toccato stop, target o scadenza."""
    notes, still = [], []
    for sig in state["open"]:
        bars = [b for b in (data.get(sig["symbol"]) or []) if b["d"] >= sig["entry_date"]]
        exit_price = reason = exit_date = None
        for i, b in enumerate(bars):
            if b["o"] <= sig["stop"] or b["l"] <= sig["stop"]:
                exit_price, reason = min(b["o"], sig["stop"]), "stop"
            elif b["o"] >= sig["target"] or b["h"] >= sig["target"]:
                exit_price, reason = max(b["o"], sig["target"]), "target"
            elif i + 1 >= cfg["max_hold_days"]:
                exit_price, reason = b["c"], "scadenza"
            if reason:
                exit_date = b["d"]
                break
        if reason:
            res = net_result(sig["entry"], exit_price, cfg)
            sig.update(exit_date=exit_date, exit=round(exit_price, 2), reason=reason,
                       result_net=res["net"], tax=res["tax"], fees=res["fees"])
            state["closed"].append(sig)
            notes.append(sig)
        else:
            if bars:
                sig["last_price"] = round(bars[-1]["c"], 2)
            still.append(sig)
    state["open"] = still
    return notes


# ---------------------------------------------------------- notifiche
def notify(cfg, title, message, priority="default"):
    topic = cfg.get("ntfy_topic")
    if not topic:
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}", data=message.encode("utf-8"),
        headers={"Title": title.encode("latin-1", "replace").decode("latin-1"),
                 "Priority": priority}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"  ! notifica fallita: {e}", file=sys.stderr)


def fmt_signal(sig, cfg):
    return (f"Compra domani all'apertura (rif. {sig['ref_price']} $)\n"
            f"Obiettivo ~{sig['target']} $ -> profitto stimato NETTO "
            f"{sig['est_profit_net']:+.0f} EUR su {cfg['position_eur']} EUR\n"
            f"Stop-loss ~{sig['stop']} $ (perdita {sig['est_loss_net']:+.0f} EUR)\n"
            f"Chiudi comunque entro {cfg['max_hold_days']} giorni di borsa.\n"
            f"Tasse 26% e costi di cambio gia' inclusi.")


# ---------------------------------------------------------------- main
def run():
    cfg = load_config()
    state = load_state()
    print("Scarico dati...")
    data = {}
    needed = set(NASDAQ_100) | {s["symbol"] for s in state["open"] + state["pending"]}
    for sym in sorted(needed):
        data[sym] = fetch(sym)
        time.sleep(0.15)
    if sum(1 for v in data.values() if v) < 10:
        print("Dati insufficienti (rete?). Esco senza modificare nulla.")
        return 1

    activate_pending(state, data, cfg)
    for sig in update_open(state, data, cfg):
        icon = {"target": "obiettivo raggiunto", "stop": "stop-loss colpito",
                "scadenza": "tempo scaduto"}[sig["reason"]]
        notify(cfg, f"CHIUDI {sig['symbol']} - {icon}",
               f"Esito stimato netto: {sig['result_net']:+.0f} EUR "
               f"(ingresso {sig['entry']} $, uscita ~{sig['exit']} $).",
               "high")

    busy = {s["symbol"] for s in state["open"] + state["pending"]}
    if market_ok():
        found = [s for sym in NASDAQ_100 if sym not in busy
                 for s in [analyze(sym, data.get(sym), cfg)] if s]
        found.sort(key=lambda s: s["score"], reverse=True)
        for sig in found[:cfg["max_new_signals_per_day"]]:
            state["pending"].append(sig)
            notify(cfg, f"COMPRA {sig['symbol']}", fmt_signal(sig, cfg), "high")
            print(f"Segnale: {sig['symbol']}")
    else:
        print("Nasdaq sotto la media a 200 giorni: nessun nuovo segnale.")

    # parametri usati dalla dashboard per il profitto netto "se chiudi ora"
    state["config"] = {k: cfg[k] for k in ("position_eur", "fx_fee_per_side", "tax_rate")}
    save_state(state)
    print(f"Fatto. Aperte: {len(state['open'])}, chiuse: {len(state['closed'])}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
