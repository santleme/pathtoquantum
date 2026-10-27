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

Fatia (b), na mesma regra: retrospectiva por era de 60 ticks
(`era_retrospectives`) — líderes ao fim da era, viradas, primeiras
falência/entrega/elos e contagens — derivada só de eventos e frames.
"""

from __future__ import annotations

import re
from statistics import median

_PROBE_RE = re.compile(r"sonda (.+?) e encontra")
_LINK_STAGE_NAMES = {"extração": 1, "refino": 2, "componentes": 3,
                      "dispositivos": 4, "supercomputador": 5}
_LINK_STAGE_RE = re.compile(
    r"elo de (extração|refino|componentes|dispositivos|supercomputador)")

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


_ERA_TICKS = 60  # a era do motor: Engine._era_summary a cada 60 ticks


def _frame_leaders(frame: dict) -> tuple:
    """(líder em caixa, líder na cadeia, elo do líder, vivas, total).

    Líderes só entre empresas vivas, como o motor (`_leader` filtra
    `alive`); empate resolve por maior valor e menor id, o mesmo
    critério do motor (`(valor, -cid)`). Sem empresas no frame, tudo
    None — sem inventar líder.
    """
    companies = frame.get("companies") or []
    alive = [c for c in companies if c.get("alive")]
    if not alive:
        return None, None, None, (len([c for c in companies
                                       if c.get("alive")])
                                  if companies else None), \
            (len(companies) if companies else None)
    cash_leader = max(alive, key=lambda c: (c.get("cash", 0),
                                            -c.get("id", 0)))
    stage_leader = max(alive, key=lambda c: (c.get("stage", 0),
                                             -c.get("id", 0)))
    return (cash_leader.get("name"), stage_leader.get("name"),
            stage_leader.get("stage", 0),
            len(alive), len(companies))


def era_retrospectives(events: list[dict], frames: list[dict]) -> list[dict]:
    """Retrospectiva por era (fatia b), ordenada por era.

    Agrupa eventos e frames por `tick // 60`. Cada era registra os
    líderes ao fim (último frame da era), as viradas de liderança
    (`rivalry`), as primeiras falência / entrega de supercomputador /
    elos da cadeia, e as contagens da era. Entrega de supercomputador
    é só o `record` "entrega um SUPERCOMPUTADOR": o recorde de elo
    ("elo de supercomputador") é marco de cadeia, não entrega.

    Limites do dado (não inventar para cobri-los):
    - a contagem é de ENTREGAS (eventos), não de unidades: o motor
      soma unidades por lote (capacidade da montadora = 2/mês) e
      emite um `record` por lote, sem campo de unidades;
    - líderes filtram só empresas vivas, enquanto o `_era_summary`
      do motor considera todas — uma falida sem comprador que
      mantivesse o maior estágio divergiria;
    - "ao fim da era" é o último frame (frames a cada 12 ticks),
      até 11 ticks defasado do estado vivo; `end_tick` é o último
      tick observado, não o fim da era.
    """
    by_era: dict[int, dict] = {}

    def era_bucket(era: int) -> dict:
        return by_era.setdefault(era, {
            "events": [], "frames": [],
        })

    for e in sorted(events, key=lambda x: x.get("tick", 0)):
        era_bucket(e.get("tick", 0) // _ERA_TICKS)["events"].append(e)
    for f in sorted(frames, key=lambda x: x.get("tick", 0)):
        era_bucket(f.get("tick", 0) // _ERA_TICKS)["frames"].append(f)

    out = []
    for era in sorted(by_era):
        bucket = by_era[era]
        evs, frs = bucket["events"], bucket["frames"]
        ticks = [e.get("tick", 0) for e in evs] + \
                [f.get("tick", 0) for f in frs]
        start_tick, end_tick = era * _ERA_TICKS, max(ticks)
        cash_leader = stage_leader = stage = None
        alive = companies = None
        if frs:
            cash_leader, stage_leader, stage, alive, companies = \
                _frame_leaders(frs[-1])
        changes, first_links = [], []
        first_bankruptcy = first_super = None
        bankruptcies = acquisitions = deliveries = 0
        for e in evs:
            kind = e.get("kind")
            if kind == "rivalry":
                changes.append({
                    "tick": e.get("tick", 0),
                    "metric": (e.get("data") or {}).get("metric"),
                    "company": e.get("company"),
                })
            elif kind == "bankruptcy":
                bankruptcies += 1
                if first_bankruptcy is None:
                    first_bankruptcy = {"company": e.get("company"),
                                        "tick": e.get("tick", 0)}
            elif kind == "acquisition":
                acquisitions += 1
            elif kind == "chain_link":
                link_stage = (e.get("data") or {}).get("stage")
                if not isinstance(link_stage, int):
                    # Crônicas antigas (ex.: viewer da corrida de
                    # nascimento) trazem data vazio: o estágio vive só
                    # no texto "elo de <nome>". Derivar daí, sem
                    # inventar: sem nome reconhecível, sem elo.
                    m = _LINK_STAGE_RE.search(e.get("text") or "")
                    link_stage = _LINK_STAGE_NAMES[m.group(1)] \
                        if m else None
                if isinstance(link_stage, int):
                    first_links.append({"stage": link_stage,
                                        "company": e.get("company"),
                                        "tick": e.get("tick", 0)})
            elif kind == "record" and "entrega um SUPERCOMPUTADOR" in \
                    (e.get("text") or ""):
                deliveries += 1
                if first_super is None:
                    first_super = {"company": e.get("company"),
                                   "tick": e.get("tick", 0)}
        parts = []
        if cash_leader is not None:
            parts.append(f"líder em caixa ao fim: {cash_leader}")
        if stage_leader is not None:
            parts.append(f"líder na cadeia ao fim: {stage_leader} "
                         f"(elo {stage})")
        if changes:
            desc = ", ".join(
                f"{c['metric']} por {c['company']} no tick {c['tick']}"
                for c in changes)
            parts.append(f"viradas de liderança: {len(changes)} ({desc})")
        if first_bankruptcy is not None:
            parts.append(f"primeira falência: "
                         f"{first_bankruptcy['company']} "
                         f"(tick {first_bankruptcy['tick']})")
        if first_super is not None:
            parts.append("primeira entrega de SUPERCOMPUTADOR: "
                         f"{first_super['company']} "
                         f"(tick {first_super['tick']})")
        if first_links:
            desc = ", ".join(
                f"elo {l['stage']} por {l['company']} "
                f"(tick {l['tick']})" for l in first_links)
            parts.append(f"primeiros elos da cadeia: {desc}")
        counts = (f"falências: {bankruptcies}; aquisições: "
                  f"{acquisitions}; entregas de supercomputador: "
                  f"{deliveries}")
        if alive is not None:
            counts += f"; empresas vivas ao fim: {alive}/{companies}"
        parts.append(counts)
        out.append({
            "era": era,
            "start_tick": start_tick,
            "end_tick": end_tick,
            "cash_leader": cash_leader,
            "stage_leader": stage_leader,
            "stage_leader_stage": stage,
            "leadership_changes": changes,
            "first_bankruptcy": first_bankruptcy,
            "first_supercomputer": first_super,
            "first_links": first_links,
            "bankruptcies": bankruptcies,
            "acquisitions": acquisitions,
            "supercomputer_deliveries": deliveries,
            "alive": alive,
            "companies": companies,
            "text": (f"RETROSPECTIVA DA ERA {era} "
                     f"(ticks {start_tick}–{end_tick}): "
                     + "; ".join(parts) + "."),
        })
    return out


def analyze_rich(events: list[dict], frames: list[dict]) -> dict:
    """Análise completa: fatia (a) + retrospectivas por era (fatia b)."""
    return {
        "deposit_disputes": detect_deposit_disputes(events),
        "price_wars": detect_price_wars(frames),
        "era_retrospectives": era_retrospectives(events, frames),
    }
