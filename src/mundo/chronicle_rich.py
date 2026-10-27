"""Crônica rica (#13, fatia a): pós-processador determinístico sobre os
eventos e frames de uma corrida já rodada.

Não toca no motor, no tick nem nos goldens: lê o que o motor já emitiu
e deriva narrativa de segundo nível. A narração em-motor (`_note_rivalry`,
`_era_summary`) cobre trocas de liderança e resumos de era; aqui entram
os dois sinais que ela não deriva:

- disputas por depósito: o mesmo depósito sondado/minerado por >= 2
  empresas, com >= 3 toques no total. Toque = evento `mine` com
  `data.deposit`, ou evento `probe` cujo texto segue o padrão
  "<empresa> sonda <depósito> e encontra...". Um toque isolado por duas
  empresas não é disputa repetida — por isso o piso de 3 toques.
- guerras de preço: queda >= 25% de uma commodity entre dois frames
  consecutivos, desde que o mercado como um todo não esteja desabando
  no mesmo passo (mediana das variações >= -10%). Colapso geral é
  regime de mercado, não guerra — sem esse filtro, o início de
  qualquer corrida (queda ampla de preços) viraria dezena de guerras
  falsas.

Limite conhecido desta fatia: disputas por elo NÃO são deriváveis do
fluxo atual de eventos — o motor emite `chain_link` só para a primeira
empresa em cada elo. Derivar disputa de elo exigiria um evento novo
(chegada posterior ao elo já dominado); fica como fatia futura, sem
inventar dado aqui.

Tudo é função pura sobre listas de dicts (o formato JSON da crônica e
dos frames), ordenado para saída determinística: disputas por
(first_tick, depósito); guerras por (trough_tick, commodity).
"""

from __future__ import annotations

import re
from statistics import median

_PROBE_RE = re.compile(r"sonda (.+?) e encontra")

_MIN_TOUCHES = 3
_WAR_DROP = 0.25        # queda mínima da commodity no passo
_MARKET_FLOOR = -0.10   # mediana do mercado não pode estar abaixo disso


def _join_names(names: list[str]) -> str:
    """'A', 'A e B', 'A, B e C' — lista em português para a narrativa."""
    if len(names) <= 2:
        return " e ".join(names)
    return ", ".join(names[:-1]) + " e " + names[-1]


def _deposit_of(event: dict) -> str | None:
    """Depósito tocado por um evento `mine` ou `probe`, ou None."""
    if event.get("kind") == "mine":
        dep = (event.get("data") or {}).get("deposit")
        if dep:
            return dep
    if event.get("kind") == "probe":
        dep = (event.get("data") or {}).get("deposit")
        if dep:
            return dep
        m = _PROBE_RE.search(event.get("text") or "")
        if m:
            return m.group(1)
    return None


def detect_deposit_disputes(events: list[dict]) -> list[dict]:
    """Disputas repetidas por depósito, ordenadas por (first_tick, nome)."""
    touches: dict[str, list[dict]] = {}
    for e in events:
        dep = _deposit_of(e)
        if dep is None or e.get("company") is None:
            continue
        touches.setdefault(dep, []).append(e)
    disputes = []
    for dep, ts in touches.items():
        companies = sorted({t["company"] for t in ts})
        if len(companies) < 2 or len(ts) < _MIN_TOUCHES:
            continue
        ticks = [t["tick"] for t in ts]
        disputes.append({
            "deposit": dep,
            "companies": companies,
            "touches": len(ts),
            "first_tick": min(ticks),
            "last_tick": max(ticks),
            "text": (f"DISPUTA: {_join_names(companies)} disputam {dep} "
                     f"({len(ts)} sondagens/minas entre os ticks "
                     f"{min(ticks)}–{max(ticks)})."),
        })
    disputes.sort(key=lambda d: (d["first_tick"], d["deposit"]))
    return disputes


def detect_price_wars(frames: list[dict]) -> list[dict]:
    """Guerras de preço idiossincráticas, ordenadas por (trough, commodity)."""
    wars = []
    for prev, cur in zip(frames, frames[1:]):
        p0, p1 = prev.get("prices") or {}, cur.get("prices") or {}
        comms = sorted(set(p0) & set(p1))
        moves = []
        for c in comms:
            if p0[c] > 0 and p1[c] >= 0:
                moves.append((c, p1[c] / p0[c] - 1))
        if not moves:
            continue
        market = median([m for _, m in moves])
        if market < _MARKET_FLOOR:
            continue  # colapso geral: regime, não guerra
        for c, move in moves:
            if move <= -_WAR_DROP:
                wars.append({
                    "commodity": c,
                    "peak_tick": prev["tick"],
                    "trough_tick": cur["tick"],
                    "peak": p0[c],
                    "trough": p1[c],
                    "drop_pct": round(-move * 100, 1),
                    "text": (f"GUERRA DE PREÇO: {c} despenca "
                             f"{round(-move * 100, 1)}% entre os ticks "
                             f"{prev['tick']}–{cur['tick']} "
                             f"({p0[c]:.1f} → {p1[c]:.1f}), enquanto o "
                             f"mercado segura."),
                })
    wars.sort(key=lambda w: (w["trough_tick"], w["commodity"]))
    return wars


def analyze_rich(events: list[dict], frames: list[dict]) -> dict:
    """Análise completa da fatia (a): disputas + guerras de preço."""
    return {
        "deposit_disputes": detect_deposit_disputes(events),
        "price_wars": detect_price_wars(frames),
    }
