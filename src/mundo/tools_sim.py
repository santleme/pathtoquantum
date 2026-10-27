"""Ferramentas simuladas com custos realistas.

As empresas USAM as ferramentas do mundo como usariam as reais — e pagam
preços na faixa dos reais. Nada aqui chama API de verdade: é o mundo
simulando a camada de serviços digitais.

- InstaSim: rede social simulada. Campanha custa CPM (US$/mil impressões,
  faixa real ~US$ 5-15). Efeito: eleva a fatia de demanda da empresa pelos
  seus dispositivos por N ticks.
- ZapSim: mensageria simulada. Custo por conversa (faixa real de API de
  mensagens ~US$ 0,03-0,08). Efeito: prioridade de conversão nas vendas
  diretas da empresa enquanto ativo.
"""
from __future__ import annotations

from dataclasses import dataclass

INSTA_CPM_USD = 9.0            # US$ por mil impressões (faixa real 5-15)
INSTA_CAMPAIGN_IMPRESSIONS = 400_000
INSTA_DURATION_TICKS = 3
ZAP_COST_PER_CONVERSATION = 0.05
ZAP_CONVERSATIONS_PER_CAMPAIGN = 60_000
ZAP_DURATION_TICKS = 2


@dataclass
class ToolEffects:
    insta_until: int = -1
    insta_strength: float = 0.0     # peso extra na divisão da demanda
    zap_until: int = -1

    def insta_active(self, tick: int) -> bool:
        return tick <= self.insta_until

    def zap_active(self, tick: int) -> bool:
        return tick <= self.zap_until


def insta_campaign_cost() -> float:
    return INSTA_CPM_USD * INSTA_CAMPAIGN_IMPRESSIONS / 1000.0


def zap_campaign_cost() -> float:
    return ZAP_COST_PER_CONVERSATION * ZAP_CONVERSATIONS_PER_CAMPAIGN
