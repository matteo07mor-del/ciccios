#!/usr/bin/env python3
"""Scanner di segnali sul Nasdaq-100 con DUE strategie indipendenti.

  BREAKOUT  swing di qualche settimana. Rottura del massimo a 20 giorni, con una
            serie di filtri pensati per scartare i falsi breakout (chiusura forte,
            volumi, base ordinata, forza relativa, no inseguimento) e con una
            conferma all'apertura del giorno dopo: se il titolo rientra sotto il
            livello rotto, il segnale viene annullato.
  RIMBALZO  swing brevissimo (massimo una settimana). Titolo in trend di fondo
            rialzista che ha avuto un ipervenduto (RSI basso) e sta risalendo,
            con incrocio rialzista del MACD, piu' conferme (Bollinger, stocastico,
            candela di rimbalzo, volumi).

- Dati giornalieri da Yahoo Finance (nessuna chiave API).
- Profitto NETTO stimato (costi eToro + tasse italiane 26%).
- Notifiche ntfy.sh con titolo [BREAKOUT] o [RIMBALZO].
- Ogni segnale e' registrato e ne viene verificato l'esito: i dati alimentano la dashboard.

Solo libreria standard: serve soltanto Python 3.9+.
"""
import json
import os
import sys
import time
import urllib.request
from collections import Counter
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

STRATEGIES = ("breakout", "rimbalzo")
LABELS = {"breakout": "BREAKOUT", "rimbalzo": "RIMBALZO"}
TAGS = {"breakout": "rocket", "rimbalzo": "arrows_counterclockwise"}


# ----------------------------------------------------------------- configurazione
DEFAULTS = {
    "position_eur": 1000, "tax_rate": 0.26, "fx_fee_per_side": 0.005,
    "leverage": 1,                 # 1 = azioni reali senza leva
    "cfd": False,                  # True = posizione CFD (costi notturni)
    "commission_per_side_eur": 0.9,  # eToro: 1-2 $ per apertura/chiusura su azioni reali
    "cfd_spread_pct": 0.0015,      # spread CFD azioni: 0,15% per operazione
    "cfd_markup_pct": 6.4,         # costo notturno CFD long azioni: 6,4% + benchmark annuo
    "cfd_benchmark_pct": 4.0,      # benchmark (tasso di riferimento): da verificare
    "ivafe_rate": 0.002,           # IVAFE 0,2% annuo sul valore (azioni reali)
}

STRATEGY_DEFAULTS = {
    "breakout": {
        "enabled": True,
        "max_new_signals_per_day": 3,
        "max_hold_days": 20,        # giorni di borsa (~4 settimane)
        "stop_atr": 2.0,
        "target_atr": 4.0,
        "min_net_profit_eur": 15,
        "require_market_uptrend": True,   # QQQ sopra la media a 200 giorni
        # --- filtri classici
        "rsi_min": 50, "rsi_max": 70,
        "min_vol_ratio": 1.4,       # volume del giorno / media 20 giorni
        # --- filtri anti falso breakout
        "break_margin_atr": 0.1,    # la CHIUSURA deve stare oltre il massimo di almeno 0,1 ATR
        "max_extension_atr": 1.5,   # ...ma non oltre 1,5 ATR (non inseguire un titolo gia' partito)
        "min_close_position": 0.7,  # chiusura nel 30% alto della candela (niente ombre di rifiuto)
        "max_bar_range_atr": 2.5,   # candela climax troppo larga = esaurimento
        "max_signal_gap_atr": 1.5,  # gap d'apertura del giorno del segnale (notizie/earnings)
        "max_base_depth_atr": 7.0,  # base dei 20 giorni ordinata (non troppo larga)
        "min_pct_of_high52": 0.90,  # prezzo entro il 10% dal massimo annuale (poca resistenza sopra)
        "require_rel_strength": True,  # meglio del Nasdaq (QQQ) negli ultimi 60 giorni
        # --- conferma all'apertura del giorno dopo
        "entry_tol_atr": 0.1,       # apre sotto (livello - 0,1 ATR) -> falso breakout, si annulla
        "entry_max_gap_atr": 1.0,   # apre oltre (chiusura + 1 ATR) -> non inseguire, si annulla
    },
    "rimbalzo": {
        "enabled": True,
        "max_new_signals_per_day": 3,
        "max_hold_days": 5,         # giorni di borsa (= 1 settimana)
        "stop_atr": 1.5,
        "target_atr": 2.0,
        "min_net_profit_eur": 15,
        "require_market_uptrend": True,
        "require_above_sma200": True,   # solo ipervenduti dentro un trend di fondo rialzista
        # --- RSI: basso e che torna a salire
        "rsi_oversold": 40, "rsi_lookback": 5, "rsi_max_now": 55,
        # --- MACD: linea MACD che taglia da sotto la linea segnale
        "macd_cross_days": 2,       # 1 = incrocio avvenuto oggi; 2 = oggi o ieri
        # --- spazio per salire e protezione dai "coltelli che cadono"
        "min_room_atr": 0.25,       # il prezzo deve stare almeno 0,25 ATR sotto la media a 20 giorni (banda centrale)
        "max_pullback_pct": 0.25,   # calo dal massimo a 20 giorni non oltre il 25%
        # --- conferme aggiuntive (ne servono almeno min_confirmations su 5)
        "stoch_oversold": 35, "bb_lookback": 5,
        "bb_near_pct": 0.10,        # Bollinger: basta il minimo entro il 10% della larghezza delle bande dal bordo inferiore
        "bb_no_new_low": True,      # Bollinger: oggi non deve fare un nuovo minimo rispetto a ieri (ha smesso di scendere)
        "min_confirmations": 2,
        # --- conferma all'apertura del giorno dopo
        "entry_min_atr": 0.5,       # apre oltre 0,5 ATR sotto la chiusura -> rimbalzo fallito, annulla
        "entry_max_gap_atr": 1.0,   # apre oltre (chiusura + 1 ATR) -> rimbalzo gia' fatto, annulla
    },
}
LEGACY_BREAKOUT_KEYS = ("max_new_signals_per_day", "max_hold_days", "stop_atr",
                        "target_atr", "min_net_profit_eur")


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    cfg = {**DEFAULTS, **{k: v for k, v in raw.items() if k not in STRATEGY_DEFAULTS}}
    legacy = {k: raw[k] for k in LEGACY_BREAKOUT_KEYS if k in raw}  # vecchio config.json piatto
    for name in STRATEGIES:
        extra = legacy if name == "breakout" else {}
        cfg[name] = {**STRATEGY_DEFAULTS[name], **extra, **raw.get(name, {})}
    if os.environ.get("NTFY_TOPIC"):  # su GitHub il topic sta nei Secrets, non nel repo
        cfg["ntfy_topic"] = os.environ["NTFY_TOPIC"]
    return cfg


def load_state():
    state = {"updated": None, "pending": [], "open": [], "closed": [], "cancelled": []}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            state.update(json.load(f))
    for key in ("pending", "open", "closed", "cancelled"):
        state.setdefault(key, [])
    return state


def save_state(state):
    state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def strat_of(sig):
    return sig.get("strategy") or "breakout"   # i segnali vecchi erano tutti breakout


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


# ----------------------------------------------------------------- indicatori
def sma(vals, n):
    return sum(vals[-n:]) / n


def sma_series(vals, n):
    """Media mobile semplice su tutta la serie (None dove non calcolabile)."""
    out = []
    for i in range(len(vals)):
        w = vals[max(0, i - n + 1):i + 1]
        out.append(sum(w) / n if i >= n - 1 and None not in w else None)
    return out


def ema_series(vals, n):
    k = 2.0 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _rsi_from(avg_gain, avg_loss):
    return 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)


def rsi_series(closes, n=14):
    """RSI di Wilder (lo stesso di eToro/TradingView). None nelle prime n barre."""
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = _rsi_from(ag, al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = _rsi_from(ag, al)
    return out


def macd_series(closes, fast=12, slow=26, signal=9):
    """Ritorna (linea MACD, linea segnale)."""
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    macd = [a - b for a, b in zip(ef, es)]
    return macd, ema_series(macd, signal)


def bollinger_at(closes, idx, n=20, k=2.0):
    """Bande di Bollinger alla barra idx (indice positivo): (centrale, alta, bassa)."""
    w = closes[idx - n + 1:idx + 1]
    mid = sum(w) / n
    sd = (sum((x - mid) ** 2 for x in w) / n) ** 0.5
    return mid, mid + k * sd, mid - k * sd


def stochastic(bars, n=14, k_smooth=3, d_smooth=3):
    """Stocastico lento (14,3,3): ritorna (%K, %D)."""
    raw = []
    for i in range(len(bars)):
        if i < n - 1:
            raw.append(None)
            continue
        w = bars[i - n + 1:i + 1]
        hh, ll = max(b["h"] for b in w), min(b["l"] for b in w)
        raw.append(50.0 if hh == ll else 100 * (bars[i]["c"] - ll) / (hh - ll))
    k = sma_series(raw, k_smooth)
    return k, sma_series(k, d_smooth)


def atr(bars, n=14):
    trs = []
    for i in range(-n, 0):
        b, prev = bars[i], bars[i - 1]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - prev["c"]), abs(b["l"] - prev["c"])))
    return sum(trs) / n


def close_position(b):
    """Dove chiude la candela nel suo range: 0 = sul minimo, 1 = sul massimo."""
    rng = b["h"] - b["l"]
    return (b["c"] - b["l"]) / rng if rng > 0 else 0.5


# ------------------------------------------------------------ costi e tasse
def est_days(p):
    """Giorni di calendario di detenzione usati nelle stime (caso peggiore: scadenza)."""
    return int(p.get("est_hold_days", round(p["max_hold_days"] * 7 / 5)))


def net_result(entry, exit_, cfg, days=0):
    """Risultato netto in EUR su una posizione di cfg['position_eur'].

    days = giorni di calendario in cui la posizione resta aperta.
    Costi inclusi:
      - conversione EUR/USD eToro (fx_fee_per_side) in apertura e in chiusura;
      - azioni reali senza leva: commissione per lato e IVAFE 0,2% annuo
        (nessun costo notturno);
      - CFD o leva > 1: spread 0,15% per lato e costo notturno
        (6,4% + benchmark) / 365 per ogni giorno, sul valore dell'esposizione.
    Tasse: 26% sulla plusvalenza; in perdita non si paga nulla
    (la minusvalenza resta compensabile per 4 anni).
    """
    pos = cfg["position_eur"]
    lev = cfg["leverage"]
    cfd = bool(cfg["cfd"]) or lev > 1
    exposure = pos * lev
    ret = exit_ / entry - 1
    gross = exposure * ret
    fx = cfg["fx_fee_per_side"]
    costs = pos * fx + max(pos + gross, 0) * fx
    if cfd:
        costs += exposure * cfg["cfd_spread_pct"] * 2
        costs += exposure * (cfg["cfd_markup_pct"] + cfg["cfd_benchmark_pct"]) / 100 / 365 * days
    else:
        costs += cfg["commission_per_side_eur"] * 2
        costs += exposure * (1 + ret) * cfg["ivafe_rate"] * days / 365
    pre_tax = gross - costs
    tax = max(pre_tax, 0) * cfg["tax_rate"]
    return {"gross": round(gross, 2), "fees": round(costs, 2),
            "tax": round(tax, 2), "pre_tax": round(pre_tax, 2),
            "net": round(pre_tax - tax, 2)}


# ------------------------------------------------------------- segnali
def _first_failed(checks):
    for name, ok in checks:
        if not ok:
            return name
    return None


def _build_signal(strategy, symbol, last, c, a, p, cfg, **extra):
    target = c + p["target_atr"] * a
    stop = c - p["stop_atr"] * a
    d = est_days(p)
    est = net_result(c, target, cfg, d)
    loss = net_result(c, stop, cfg, d)
    sig = {"strategy": strategy, "symbol": symbol, "signal_date": last["d"],
           "ref_price": round(c, 2), "atr": round(a, 4),
           "target": round(target, 2), "stop": round(stop, 2),
           "est_profit_net": est["net"], "est_loss_net": loss["net"]}
    sig.update(extra)
    return sig, est["net"]


def analyze_breakout(symbol, bars, cfg, bench):
    """Breakout del massimo a 20 giorni. Ritorna (segnale|None, filtro che ha scartato)."""
    p = cfg["breakout"]
    if not bars or len(bars) < 210:
        return None, "dati insufficienti"
    closes = [b["c"] for b in bars]
    vols = [b["v"] for b in bars]
    last, prev = bars[-1], bars[-2]
    c = last["c"]
    s50, s200 = sma(closes, 50), sma(closes, 200)
    s50_10d_ago = sum(closes[-60:-10]) / 50
    r = rsi_series(closes)[-1]
    base = bars[-21:-1]
    level = max(b["h"] for b in base)             # massimo dei 20 giorni PRIMA di oggi
    base_low = min(b["l"] for b in base)
    high52 = max(b["h"] for b in bars)
    a = atr(bars)
    vol_ratio = last["v"] / sma(vols[:-1], 20)
    cpos = close_position(last)
    rng = last["h"] - last["l"]
    gap = last["o"] - prev["c"]

    rel = None
    if bench and len(bench) > 61 and len(closes) > 61:
        rel = (c / closes[-61] - 1) - (bench[-1] / bench[-61] - 1)

    checks = [
        ("trend", c > s50 > s200 and s50 > s50_10d_ago),
        ("breakout (chiusura oltre il massimo)", c >= level + p["break_margin_atr"] * a),
        ("non inseguire (gia' esteso)", c - level <= p["max_extension_atr"] * a),
        ("chiusura forte", c > last["o"] and cpos >= p["min_close_position"]),
        ("volumi", vol_ratio >= p["min_vol_ratio"]),
        ("RSI", p["rsi_min"] <= r <= p["rsi_max"]),
        ("candela climax", rng <= p["max_bar_range_atr"] * a),
        ("gap da notizie", gap <= p["max_signal_gap_atr"] * a),
        ("base ordinata", (level - base_low) <= p["max_base_depth_atr"] * a),
        ("vicino ai massimi annuali", c >= p["min_pct_of_high52"] * high52),
        ("forza relativa", (not p["require_rel_strength"]) or rel is None or rel > 0),
    ]
    failed = _first_failed(checks)
    if failed:
        return None, failed

    score = (vol_ratio + cpos + (c / s50 - 1) * 5 + (rel or 0) * 5
             + (70 - abs(r - 60)) / 20)
    why = [f"chiusura {c:.2f} sopra il massimo a 20 gg ({level:.2f})",
           f"volumi x{vol_ratio:.1f}", f"chiusura a {cpos * 100:.0f}% della candela"]
    if rel is not None:
        why.append(f"meglio di QQQ di {rel * 100:+.1f}% (60 gg)")
    sig, net = _build_signal(
        "breakout", symbol, last, c, a, p, cfg,
        rsi=round(r, 1), vol_ratio=round(vol_ratio, 2), level=round(level, 2),
        entry_min=round(level - p["entry_tol_atr"] * a, 2),
        entry_max=round(c + p["entry_max_gap_atr"] * a, 2),
        score=round(score, 2), why=why)
    if net < p["min_net_profit_eur"]:
        return None, "profitto netto minimo"
    return sig, None


def analyze_rimbalzo(symbol, bars, cfg, bench):
    """Rimbalzo da ipervenduto (orizzonte max 1 settimana)."""
    p = cfg["rimbalzo"]
    if not bars or len(bars) < 210:
        return None, "dati insufficienti"
    n = len(bars)
    closes = [b["c"] for b in bars]
    vols = [b["v"] for b in bars]
    last = bars[-1]
    c = last["c"]
    a = atr(bars)
    s200 = sma(closes, 200)
    vol_ratio = last["v"] / sma(vols[:-1], 20)
    cpos = close_position(last)

    # RSI: e' stato basso di recente e adesso risale
    r_s = rsi_series(closes)
    r, r_prev = r_s[-1], r_s[-2]
    r_low = min(r_s[-p["rsi_lookback"]:])

    # filtri economici prima: evitano di calcolare MACD/stocastico sulla gran parte dei titoli
    for name, ok in (("trend di fondo (sopra SMA200)", (not p["require_above_sma200"]) or c > s200),
                     ("RSI ipervenduto", r_low <= p["rsi_oversold"]),
                     ("RSI che risale", r > r_prev and r <= p["rsi_max_now"])):
        if not ok:
            return None, name

    # MACD: la linea MACD taglia la linea segnale DAL BASSO verso l'alto
    macd, msig = macd_series(closes)
    cross_idx = None
    for k in range(1, p["macd_cross_days"] + 1):
        i = n - k
        if macd[i - 1] <= msig[i - 1] and macd[i] > msig[i]:
            cross_idx = i
            break
    macd_ok = cross_idx is not None and macd[-1] > msig[-1]

    # spazio verso la media a 20 giorni e calo dal massimo recente
    mid = bollinger_at(closes, n - 1)[0]
    high20 = max(b["h"] for b in bars[-20:])
    pullback = (high20 - c) / high20

    checks = [
        ("trend di fondo (sopra SMA200)", (not p["require_above_sma200"]) or c > s200),
        ("RSI ipervenduto", r_low <= p["rsi_oversold"]),
        ("RSI che risale", r > r_prev and r <= p["rsi_max_now"]),
        ("incrocio MACD", macd_ok),
        ("spazio verso la media", mid - c >= p["min_room_atr"] * a),
        ("calo eccessivo", pullback <= p["max_pullback_pct"]),
    ]
    failed = _first_failed(checks)
    if failed:
        return None, failed

    # conferme aggiuntive
    conf = []
    def near_lower(j):
        _, up_j, low_j = bollinger_at(closes, n - j)
        return bars[n - j]["l"] <= low_j + p["bb_near_pct"] * (up_j - low_j)
    touched = any(near_lower(j) for j in range(1, p["bb_lookback"] + 1))
    prev = bars[-2]
    stopped_falling = (not p["bb_no_new_low"]) or last["l"] >= prev["l"]
    if touched and c > prev["c"] and stopped_falling:
        conf.append("Bollinger: vicino/sotto la banda inferiore, ha smesso di scendere e risale")
    k_s, d_s = stochastic(bars)
    st_cross = any(k_s[n - j] > d_s[n - j] and k_s[n - j - 1] <= d_s[n - j - 1]
                   for j in (1, 2))
    if st_cross and min(k_s[-3:]) <= p["stoch_oversold"]:
        conf.append("stocastico: incrocio rialzista da ipervenduto")
    if c > last["o"] and cpos >= 0.6:
        conf.append("candela di rimbalzo (chiude verde in alto)")
    if vol_ratio >= 1.0:
        conf.append(f"volumi sopra media (x{vol_ratio:.1f})")
    if macd[cross_idx] < 0:
        conf.append("MACD incrocia sotto lo zero (pullback profondo)")
    if len(conf) < p["min_confirmations"]:
        return None, "conferme insufficienti"

    score = (len(conf) + (p["rsi_oversold"] - r_low) / 10
             + (mid - c) / a * 0.3 + min(vol_ratio, 3) * 0.3)
    why = [f"RSI {r_low:.0f} -> {r:.0f}", "MACD incrocia al rialzo il segnale"] + conf
    sig, net = _build_signal(
        "rimbalzo", symbol, last, c, a, p, cfg,
        rsi=round(r, 1), rsi_low=round(r_low, 1), vol_ratio=round(vol_ratio, 2),
        level=round(mid, 2), confirmations=len(conf),
        entry_min=round(c - p["entry_min_atr"] * a, 2),
        entry_max=round(c + p["entry_max_gap_atr"] * a, 2),
        score=round(score, 2), why=why)
    if net < p["min_net_profit_eur"]:
        return None, "profitto netto minimo"
    return sig, None


ANALYZERS = {"breakout": analyze_breakout, "rimbalzo": analyze_rimbalzo}


def market_ok(bench):
    if not bench or len(bench) < 200:
        return False
    closes = [b["c"] for b in bench]
    return closes[-1] > sma(closes, 200)


# ------------------------------------------------------ tracciamento esiti
def activate_pending(state, data, cfg):
    """Il segnale diventa operazione alla prima barra successiva (ingresso = apertura),
    purche' l'apertura confermi il segnale: altrimenti viene annullato.
    Ritorna la lista dei segnali annullati."""
    still, cancelled = [], []
    for sig in state["pending"]:
        bars = data.get(sig["symbol"]) or []
        nxt = next((b for b in bars if b["d"] > sig["signal_date"]), None)
        if not nxt:
            still.append(sig)
            continue
        entry = nxt["o"]
        lo, hi = sig.get("entry_min"), sig.get("entry_max")
        code = None
        if lo is not None and entry < lo:
            code = "sotto_livello"      # breakout: rientrato nel range; rimbalzo: apertura debole
        elif hi is not None and entry > hi:
            code = "gap_alto"           # troppo lontano dal segnale: sarebbe inseguire
        if code:
            sig.update(cancel_date=nxt["d"], open=round(entry, 2), cancel_reason=code)
            state["cancelled"].append(sig)
            cancelled.append(sig)
            continue
        p = cfg[strat_of(sig)]
        sig.update(entry_date=nxt["d"], entry=round(entry, 2),
                   stop=round(entry - p["stop_atr"] * sig["atr"], 2),
                   target=round(entry + p["target_atr"] * sig["atr"], 2))
        state["open"].append(sig)
    state["pending"] = still
    state["cancelled"] = state["cancelled"][-60:]
    return cancelled


def update_open(state, data, cfg):
    """Chiude le operazioni che hanno toccato stop, target o scadenza."""
    notes, still = [], []
    for sig in state["open"]:
        max_hold = cfg[strat_of(sig)]["max_hold_days"]
        bars = [b for b in (data.get(sig["symbol"]) or []) if b["d"] >= sig["entry_date"]]
        exit_price = reason = exit_date = None
        for i, b in enumerate(bars):
            if b["o"] <= sig["stop"] or b["l"] <= sig["stop"]:
                exit_price, reason = min(b["o"], sig["stop"]), "stop"
            elif b["o"] >= sig["target"] or b["h"] >= sig["target"]:
                exit_price, reason = max(b["o"], sig["target"]), "target"
            elif i + 1 >= max_hold:
                exit_price, reason = b["c"], "scadenza"
            if reason:
                exit_date = b["d"]
                break
        if reason:
            held = (datetime.strptime(exit_date, "%Y-%m-%d")
                    - datetime.strptime(sig["entry_date"], "%Y-%m-%d")).days
            res = net_result(sig["entry"], exit_price, cfg, held)
            sig.update(exit_date=exit_date, exit=round(exit_price, 2), reason=reason,
                       result_net=res["net"], tax=res["tax"], fees=res["fees"], days_held=held)
            state["closed"].append(sig)
            notes.append(sig)
        else:
            if bars:
                sig["last_price"] = round(bars[-1]["c"], 2)
                sig["bars_held"] = len(bars)
            still.append(sig)
    state["open"] = still
    return notes


# ---------------------------------------------------------- notifiche
def notify(cfg, title, message, priority="default", tags=None):
    topic = cfg.get("ntfy_topic")
    if not topic:
        return
    headers = {"Title": title.encode("latin-1", "replace").decode("latin-1"),
               "Priority": priority}
    if tags:
        headers["Tags"] = tags
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=message.encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"  ! notifica fallita: {e}", file=sys.stderr)


def _costs_line(cfg, p):
    kind = "interessi notturni CFD" if (cfg["cfd"] or cfg["leverage"] > 1) else "IVAFE"
    return (f"Incluso: tasse 26%, cambio, commissioni e {kind} "
            f"(stima su {est_days(p)} giorni).")


def fmt_signal(sig, cfg):
    p = cfg[strat_of(sig)]
    if strat_of(sig) == "breakout":
        head = (f"Chiusura {sig['ref_price']} $ sopra il massimo a 20 giorni "
                f"({sig['level']} $), volumi x{sig['vol_ratio']}.")
        rule = (f"Compra domani all'apertura SOLO se apre tra {sig['entry_min']} e "
                f"{sig['entry_max']} $. Sotto = falso breakout (salta); "
                f"sopra = stai inseguendo (salta).")
        horizon = f"Chiudi comunque entro {p['max_hold_days']} giorni di borsa."
    else:
        head = (f"RSI {sig['rsi_low']} -> {sig['rsi']} e MACD incrocia al rialzo il segnale. "
                f"Conferme: {sig['confirmations']}/5.")
        rule = (f"Compra domani all'apertura SOLO se apre tra {sig['entry_min']} e "
                f"{sig['entry_max']} $. Sotto = rimbalzo fallito (salta); "
                f"sopra = rimbalzo gia' fatto (salta).")
        horizon = (f"Chiudi comunque entro {p['max_hold_days']} giorni di borsa "
                   f"(max 1 settimana). Media a 20 gg ~{sig['level']} $.")
    risk = (f"Dopo l'acquisto: stop = prezzo - {p['stop_atr'] * sig['atr']:.2f} $, "
            f"obiettivo = prezzo + {p['target_atr'] * sig['atr']:.2f} $ (ATR {sig['atr']:.2f}).")
    return (f"{head}\n{rule}\n"
            f"Obiettivo ~{sig['target']} $ -> profitto stimato NETTO "
            f"{sig['est_profit_net']:+.0f} EUR su {cfg['position_eur']} EUR\n"
            f"Stop-loss ~{sig['stop']} $ (perdita {sig['est_loss_net']:+.0f} EUR)\n"
            f"{risk}\n{horizon}\n{_costs_line(cfg, p)}")


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
    bench = fetch("QQQ")

    # 1) conferma all'apertura dei segnali di ieri
    for sig in activate_pending(state, data, cfg):
        label = LABELS[strat_of(sig)]
        why = ("ha aperto sotto il livello (falso breakout evitato)"
               if strat_of(sig) == "breakout" and sig["cancel_reason"] == "sotto_livello"
               else "apertura debole, rimbalzo non confermato"
               if sig["cancel_reason"] == "sotto_livello"
               else "gap troppo alto, non inseguire")
        print(f"Annullato {label} {sig['symbol']}: {why}")
        notify(cfg, f"[{label}] ANNULLATO {sig['symbol']}",
               f"Il segnale di ieri non e' confermato: {why} "
               f"(apertura {sig['open']} $). Non comprare.", "low", TAGS[strat_of(sig)])

    # 2) esiti delle operazioni aperte
    for sig in update_open(state, data, cfg):
        label = LABELS[strat_of(sig)]
        icon = {"target": "obiettivo raggiunto", "stop": "stop-loss colpito",
                "scadenza": "tempo scaduto"}[sig["reason"]]
        notify(cfg, f"[{label}] CHIUDI {sig['symbol']} - {icon}",
               f"Esito stimato netto: {sig['result_net']:+.0f} EUR "
               f"(ingresso {sig['entry']} $, uscita ~{sig['exit']} $).",
               "high", TAGS[strat_of(sig)])

    # 3) nuovi segnali, strategia per strategia
    busy = {s["symbol"] for s in state["open"] + state["pending"]}
    uptrend = market_ok(bench)
    for name in STRATEGIES:
        p = cfg[name]
        if not p["enabled"]:
            continue
        if p["require_market_uptrend"] and not uptrend:
            print(f"[{LABELS[name]}] Nasdaq sotto la media a 200 giorni: nessun nuovo segnale.")
            continue
        found, funnel = [], Counter()
        bench_closes = [b["c"] for b in bench] if bench else None
        for sym in NASDAQ_100:
            if sym in busy:
                continue
            sig, failed = ANALYZERS[name](sym, data.get(sym), cfg, bench_closes)
            if sig:
                found.append(sig)
            else:
                funnel[failed] += 1
        found.sort(key=lambda s: s["score"], reverse=True)
        for sig in found[:p["max_new_signals_per_day"]]:
            state["pending"].append(sig)
            busy.add(sig["symbol"])
            notify(cfg, f"[{LABELS[name]}] COMPRA {sig['symbol']}",
                   fmt_signal(sig, cfg), "high", TAGS[name])
            print(f"[{LABELS[name]}] Segnale: {sig['symbol']}")
        if not found:
            top = ", ".join(f"{k} ({v})" for k, v in funnel.most_common(3))
            print(f"[{LABELS[name]}] Nessun segnale. Filtri piu' selettivi: {top}")

    # parametri usati dalla dashboard per il profitto netto "se chiudi ora"
    state["config"] = {k: cfg[k] for k in (
        "position_eur", "fx_fee_per_side", "tax_rate", "leverage", "cfd",
        "commission_per_side_eur", "cfd_spread_pct", "cfd_markup_pct",
        "cfd_benchmark_pct", "ivafe_rate")}
    state["config"]["est_hold_days"] = {n: est_days(cfg[n]) for n in STRATEGIES}
    state["config"]["max_hold_days"] = {n: cfg[n]["max_hold_days"] for n in STRATEGIES}
    save_state(state)
    print(f"Fatto. Aperte: {len(state['open'])}, chiuse: {len(state['closed'])}, "
          f"annullate (totale recente): {len(state['cancelled'])}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
