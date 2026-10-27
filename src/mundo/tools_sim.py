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
- VidSim: estúdio de vídeo/conteúdo simulado (v1). Produzir vídeo curto
  comercial custa, no mercado real, ~US$ 1-25 mil por peça (produtoras e
  freelancers) e o CPM de vídeo é bem maior que o de feed. Efeito:
  demanda maior e mais longa que a do InstaSim, focada nos produtos de
  elo alto (dispositivo e supercomputador).
- LojaSim: marketplace simulado (v1). Marketplaces reais cobram comissão
  de ~8-16% sobre a venda (referral Amazon 8-15%; Mercado Livre ~11-16%
  em eletrônicos) mais mensalidade da loja. Efeito: conversão maior nas
  vendas de dispositivos às cidades, pagando a taxa sobre cada venda.
"""
from __future__ import annotations

from dataclasses import dataclass

INSTA_CPM_USD = 9.0            # US$ por mil impressões (faixa real 5-15)
INSTA_CAMPAIGN_IMPRESSIONS = 400_000
INSTA_DURATION_TICKS = 3
ZAP_COST_PER_CONVERSATION = 0.05
ZAP_CONVERSATIONS_PER_CAMPAIGN = 60_000
ZAP_DURATION_TICKS = 2
VID_VIDEOS_PER_CAMPAIGN = 4
VID_COST_PER_VIDEO = 6_000.0   # US$/vídeo curto comercial (faixa real 1k-25k)
VID_DURATION_TICKS = 6
VID_DEMAND_WEIGHT = 2.8        # multiplicador na fatia de demanda (InstaSim: 2.2)
LOJA_FEE_PCT = 0.13            # comissão sobre vendas (faixa real 8-16%)
LOJA_STORE_COST = 5_000.0      # abertura/mensalidade da loja por ciclo
LOJA_DURATION_TICKS = 6
LOJA_DEMAND_WEIGHT = 1.6       # conversão na prateleira (ZapSim: 1.3)


@dataclass
class ToolEffects:
    insta_until: int = -1
    insta_strength: float = 0.0     # peso extra na divisão da demanda
    zap_until: int = -1
    vid_until: int = -1
    loja_until: int = -1

    def insta_active(self, tick: int) -> bool:
        return tick <= self.insta_until

    def zap_active(self, tick: int) -> bool:
        return tick <= self.zap_until

    def vid_active(self, tick: int) -> bool:
        return tick <= self.vid_until

    def loja_active(self, tick: int) -> bool:
        return tick <= self.loja_until


def insta_campaign_cost() -> float:
    return INSTA_CPM_USD * INSTA_CAMPAIGN_IMPRESSIONS / 1000.0


def zap_campaign_cost() -> float:
    return ZAP_COST_PER_CONVERSATION * ZAP_CONVERSATIONS_PER_CAMPAIGN


def vid_campaign_cost() -> float:
    return VID_COST_PER_VIDEO * VID_VIDEOS_PER_CAMPAIGN


def loja_store_cost() -> float:
    return LOJA_STORE_COST
