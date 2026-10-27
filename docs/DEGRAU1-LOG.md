# DEGRAU 1 — LOG DE FASES
### Portões medidos, fase a fase (protocolo: docs/DEGRAU1-DESIGN.md §5)

## Fase 1 — Python oficial enxuto (26/10/2026)

**Entregue**
- Goldens §3.5 congelados como teste executável (`tests/test_golden.py`):
  SHA-256 do `state_dict` completo, calculados sobre o motor pré-Degrau 1
  (seed 42: n=8×24 `e01923e1…`, n=100×24 `24b1b3bf…`, n=8×120 `74412ded…`,
  n=8×24 mundo builtin `83e1fa20…`).
- Fundação struct-of-arrays onde o design manda: `chain.COMMODITY_INDEX`
  (índice inteiro por commodity) + `companies.StockBook` — estoques viram
  UM array plano por empresa (a linha da tabela `stocks (N, C)`), com
  protocolo Mapping completo por nome por fora. Caminhos quentes por
  índice: `_market` (comércio interno e vendas às cidades), `_convert`,
  `_produce` (mina/fábricas) e a transferência de ativos na aquisição.
- `mundo/tables.py`: projeção SoA somente-leitura (`cash (N,)`,
  `stocks (N, C)`, `prices (C,)`, `anchors (C,)`) — a ponte do núcleo
  nativo (Fase 5) e de drivers de treino; provado que não muta o motor.
- `mundo/driver.py`: driver de episódios multiprocesso — specs
  independentes, resultados **na ordem das specs** (agregação
  determinística), série == paralelo == Engine direto (teste).

**Portão medido** (VM de dev, 2 vCPU, Python 3.12.3)
- Suíte: **61/61 verde**; goldens **bit-idênticos** (4/4) após o refactor.
- ms/tick pós-refactor: n=8 **0,334** · n=100 **2,216** — neutro contra o
  baseline do Portão 0 (2,042 a n=100; dentro do ruído entre protocolos).
  Confirma o Portão 0: o ganho da Fase 1 NÃO é micro-otimização de tick.
- Driver (episódios de 120 ticks): n=8 serial **19,5 ep/s** → 4 processos
  **21,0 ep/s** (1,08×); n=100 serial **2,8 ep/s** → **3,6 ep/s** (1,27×).
  A VM tem **2 vCPU** — 4 processos sobrescrevem o hardware; o teto aqui
  é núcleo, não driver (no Kaggle, 4 vCPU, espera-se ~3–4×).
- Projeção recalculada (10M ticks, n=100, mundo rico ×2,5, ÷4 proc.):
  **≈231 min > 45 min** — a Fase 5 (núcleo nativo) segue necessária e
  aberta pelo Portão 0; a fila Fases 2–4 não muda.

**Fora da fase (registrado, não forçado)**
- Hotspot 5 (`_emit_flows` enxuto) muda o payload do evento `flows`:
  continua fora do pacote bit-idêntico, aguardando decisão de regravar
  goldens (design §3.5).
- Hotspot 3 (total corrente no `_market`): ~1,03× sem garantia de
  bit-identidade por construção — não entrou (Portão 0 já o havia
  reprovado como otimização).

## Fase 2 — B1 Mercado vivo (26/10/2026)

**Entregue**
- `Engine(market_v2=True, market_params=None)` — flag nova, desligada por
  padrão. Desligado: nenhum RNG extra, nenhum bloco no `state_dict`,
  goldens da Fase 1 **bit-idênticos** (suíte confirma).
- Mecânica (design §4/B1): demanda das cidades elástica
  `D = D0·(p/p*)^(−ε)·saz(t)` (ε: lítio 0,3; cobre 0,4; ferro 0,5;
  componentes 0,7; device 1,0; supercomputador 1,2); sazonalidade anual
  leve; preço justo = âncora × `exp(−γ(I−I*))` × ruído, com a cobertura
  `I` = estoque AGREGADO ÷ EMA de demanda — pública estilo LME, estoques
  por empresa seguem privados (fog-of-war testado); regimes Markov
  boom/normal/bust com durações médias e deriva de âncora calibradas
  (lítio: boom 24m/bust 30m, σ 9%/mês — ciclo USGS 2020–2025); banda de
  preço [0,25×; 6×] **da âncora** (a antiga, do base fixo, morreu).
  O ajuste por desequilíbrio continua, sobre a demanda elástica.
- Parâmetros como DADO: `data/market_params.json` com nota de
  calibração e fontes por commodity (USGS MCS 2025, LME, World Bank
  Pink Sheet) + loader/validador `mundo/marketdata.py` com fallback
  embutido idêntico (o bundle do Kaggle não carrega `data/`) — teste
  garante que arquivo e fallback nunca divergem.
- Acoplamento preparado (sem B3): âncora `p*` exposta como série
  pública — `engine.anchors`, `result()["market"]`, frames com bloco
  `market` (âncora/cobertura públicas; regime visível só na visão de
  Deus dos frames — empresas inferem do preço) e `tables.anchors_table`.
- Crônica: kinds novos `market_regime` (só entradas em boom/bust) e
  `price_record` (extremo da janela de 24 meses) registrados em
  `chronicle.py`. **Lição de calibração:** a primeira versão gerava
  172 recordes/120 ticks (toda derrapada longa vira "recorde" mensal =
  ruído, viola o princípio B0.4); com recordes por **episódio**
  (reversão ≥5% do extremo encerra o episódio) caiu para **26/120
  ticks** na seed 42, com 27 viradas de regime.
- `driver.EpisodeSpec` ganhou `market_v2`/`market_params`.
- Notebook de veredito **preparado, não lançado**:
  `notebooks/veredito-b1.ipynb` — corridas pareadas on/off (seeds
  42/7/11/23, 120 ticks), comparativo de vivacidade (eventos
  salientes, rivalidades, amplitude de preços) + placar + checagem de
  ledger, com regra de aprovação pré-registrada impressa pelo próprio
  notebook. O lançamento no Kaggle é do agente pai (precisa de bundle
  novo do fonte: src3).

**Portão medido** (VM de dev, 2 vCPU)
- Suíte: **76/76 verde** (61 + 15 do B1: ledgers, fog-of-war, replay,
  snapshot/restore cruzando viradas de regime forçadas, banda da
  âncora, episódios de recorde, arquivo==fallback).
- Custo do B1: a estimativa "<1–2% do tick" do estudo/design **não se
  confirmou de primeira** (+12% medido a n=100). Causa: a cobertura
  exige a agregação de estoques que o mercado clássico não fazia, e a
  matemática por commodity é custo fixo por tick. Após otimização
  (totais uma vez por tick via SoA, sazonalidade uma vez por tick,
  fórmulas inline no caminho quente), o custo fixo é ~0,1 ms/tick e as
  medições intercaladas a n=100 caíram para dentro do ruído desta VM
  (medianas entre −8% e +9% conforme a rodada — a VM tem 2 vCPU
  compartilhadas). **Portão de ≤2%: não comprovado nesta VM**; a
  medição limpa fica para a corrida de veredito no Kaggle (4 vCPU).
  Impacto na projeção do Portão 0: desprezível (213 → ~230 min no pior
  caso; a Fase 5 segue aberta e necessária pelo mesmo motivo).

**Fora da fase**
- Calibração fina contra momentos das séries reais (volatilidade,
  autocorrelação, duração de ciclo simulados × USGS/LME): é o notebook
  de calibração previsto no design §5/Fase 2 — o de veredito acima
  mede vivacidade; momentos estatísticos ficam como próximo notebook.
- Observação local (seed 42, 120 ticks): o lítio refinado bate o piso
  da banda no ano 1 (estoque sobe rápido, demanda elástica encolhe com
  preço alto) — comportamento a julgar na calibração, não corrigido
  por achismo aqui.
- B3/B4a/B2: fases seguintes, sem código adiantado além do gancho da
  âncora pública.
