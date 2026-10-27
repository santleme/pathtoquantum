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
