"""Statistiche sulle operazioni chiuse: solo libreria standard.

Servono a distinguere un vantaggio reale dalla fortuna: intervalli di confidenza (Wilson per la
percentuale di vittorie, bootstrap per il netto medio), profit factor, drawdown e la percentuale di
vittorie necessaria per andare in pareggio dopo costi e tasse."""
import math
import random


def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def bootstrap_mean(xs, n_boot=1000, seed=7):
    if len(xs) < 2:
        return (xs[0], xs[0]) if xs else (0.0, 0.0)
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def max_drawdown(nets):
    peak = cum = worst = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return round(worst, 2)


def summarize(trades, min_n=30):
    nets = [t["result_net"] for t in sorted(trades, key=lambda t: t["exit_date"])]
    n = len(nets)
    out = {"n": n, "verdict": "nessun dato"}
    if not n:
        return out
    wins, losses = [x for x in nets if x > 0], [x for x in nets if x <= 0]
    w_lo, w_hi = wilson(len(wins), n)
    a_lo, a_hi = bootstrap_mean(nets)
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    out.update(win=round(100 * len(wins) / n, 1), win_lo=round(100 * w_lo, 1), win_hi=round(100 * w_hi, 1),
               avg=round(sum(nets) / n, 2), avg_lo=round(a_lo, 2), avg_hi=round(a_hi, 2),
               pf=round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
               mdd=max_drawdown(nets), avg_win=round(avg_w, 2), avg_loss=round(avg_l, 2),
               be_win=round(100 * -avg_l / (avg_w - avg_l), 1) if wins and losses and avg_w > avg_l else None)
    if n < min_n:
        out["verdict"] = "campione troppo piccolo"
    elif a_lo > 0:
        out["verdict"] = "vantaggio probabile"
    elif a_hi < 0:
        out["verdict"] = "in perdita"
    else:
        out["verdict"] = "non distinguibile dal caso"
    return out
