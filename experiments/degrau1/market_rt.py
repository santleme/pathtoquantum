"""Variante do hotspot 3 (`_market` com total corrente) — NÃO bit-idêntica
por construção, isolada para medição.

É o `_market` original com uma única mudança: `total_left` deixa de
ser `sum(offered_left.values())` recomputado por comprador e passa a
ser mantido por subtração a cada share. A ordem das somas muda, logo
o resultado pode divergir no último ulp e contaminar `fill`/shares —
o spike mede (a) se os fixtures de equivalência sobrevivem na
prática e (b) quanto tempo a variante economiza. A decisão de
adotá-la (regravando goldens) é do fundador, não deste spike.
"""
from __future__ import annotations

from mundo import chain
from mundo.engine import Engine, _COMMODITIES_SORTED
from mundo.tools_sim import LOJA_DEMAND_WEIGHT, LOJA_FEE_PCT, VID_DEMAND_WEIGHT

_orig_market = Engine._market


def _market_rt(self):
    tick = self.tick
    for commodity in _COMMODITIES_SORTED:
        price = self.prices[commodity]
        offers, buys = [], []
        for c in self.companies:
            if not c.alive:
                continue
            q = c._offers.get(commodity, 0.0)
            if q > 0.001:
                offers.append((c, q))
            buys.append((c, c._buys.get(commodity, 0.0)))
        total_supply = sum(q for _, q in offers)
        if total_supply <= 0:
            continue
        # 1) comércio entre empresas — total_left mantido por subtração
        internal_demand = sum(q for _, q in buys)
        offered_left = {c.cid: q for c, q in offers}
        total_left = total_supply
        for buyer, want in sorted(buys, key=lambda x: x[0].cid):
            if want <= 0:
                continue
            if total_left <= 0:
                break
            fill = min(want, total_left)
            for seller, q in offers:
                if seller is buyer or offered_left[seller.cid] <= 0:
                    continue
                share = fill * (offered_left[seller.cid] / total_left)
                share = min(share, offered_left[seller.cid],
                            buyer.cash / price if price > 0 else 0.0)
                if share <= 0.0001:
                    continue
                seller.stocks[commodity] -= share
                buyer.stocks[commodity] += share
                seller.cash += share * price
                buyer.cash -= share * price
                self._flow(seller.cid, "trade_in", share * price)
                self._flow(buyer.cid, "trade_out", -share * price)
                offered_left[seller.cid] -= share
                total_left -= share
        # 2) demanda das cidades sobre o que restou
        city_q = chain.CITY_DEMAND.get(commodity, 0.0) \
            * self._demand_factor(commodity)
        if city_q > 0 and total_left > 0:
            weights = {}
            for seller, _ in offers:
                w = offered_left[seller.cid]
                if seller.tools.insta_active(tick) and commodity == "device":
                    w *= 2.2
                if seller.tools.vid_active(tick) \
                        and commodity in ("device", "supercomputer"):
                    w *= VID_DEMAND_WEIGHT
                if seller.tools.zap_active(tick):
                    w *= 1.3
                if seller.tools.loja_active(tick) and commodity == "device":
                    w *= LOJA_DEMAND_WEIGHT
                weights[seller.cid] = w
            wsum = sum(weights.values())
            for seller, _ in offers:
                if wsum <= 0:
                    break
                qty = min(offered_left[seller.cid],
                          city_q * weights[seller.cid] / wsum)
                if qty <= 0.0001:
                    continue
                seller.stocks[commodity] -= qty
                seller.cash += qty * price
                self._flow(seller.cid, "city_sales", qty * price)
                self.money_in += qty * price
                self.ledger_mass[commodity]["sold_external"] += qty
                offered_left[seller.cid] -= qty
                total_left -= qty
                if commodity == "device" and seller.tools.loja_active(tick):
                    fee = qty * price * LOJA_FEE_PCT
                    seller.cash -= fee
                    self.money_out += fee
                    self._flow(seller.cid, "spend_tools", -fee)
        # 3) ajuste de preço por desequilíbrio
        demand = internal_demand + city_q
        ratio = (demand - total_supply) / max(demand, total_supply, 1.0)
        factor = min(1.35, max(0.72, 1.0 + 0.10 * ratio))
        base = chain.BASE_PRICES[commodity]
        self.prices[commodity] = min(base * 3.0,
                                     max(base * 0.3, price * factor))


def apply() -> None:
    Engine._market = _market_rt


def remove() -> None:
    Engine._market = _orig_market
