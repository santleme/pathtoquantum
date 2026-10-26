# PATH TO QUANTUM — design v0

> Nome dado pelo fundador (o projeto nasceu como "Mundo Autônomo").
> A jornada do mundo tem eras nomeadas — §"As eras do mundo", abaixo.
> Documentos irmãos: `docs/PRD.md` (produto) e `docs/SDD.md` (sistema).

## A visão (nas palavras do fundador)

"Eu sou o Deus do mundo. Eu quero controlar, eu quero construir o mundo,
soltar as empresas e assim consigo assistir a história emergir."

"O mundo é a Terra de verdade, com unidades reais."

"Empresas autônomas que conseguem fechar a cadeia de produção" — não só
mineradoras: empresas de IA que extraem, produzem, vendem e competem, até
fechar cadeias de produção inteiras sozinhas, sem alguém otimizando por fora.

"Integrações simuladas: um WhatsApp simulado, um Instagram simulado —
ferramentas que existem, só que simuladas. A empresa usa o Instagram para
automatizar mensagens, usa um estúdio para produzir vídeos, e os custos dela
são dados certos, de simulações reais, com coisas reais."

Se dinheiro não existisse, é isto que ele construiria. Então é isto.

## O que o v0 é

- **Terra real**: grade lat/lon da América do Sul; depósitos reais em
  posições reais (Atacama, Uyuni, Escondida, Carajás, Quadrilátero,
  pré-sal, Vaca Muerta...); cidades reais como mercados. Toneladas e US$.
- **Empresas autônomas (8)**: caixa, sede, personalidade (agressividade,
  risco, obsessão por verticalizar, marketing) e política heurística —
  nenhum LLM por tick. Elas sondam (o subsolo é fog-of-war: teor e
  tamanho só existem para quem sondou), reivindicam, mineram, refinam,
  fabricam, compram de rivais, falem e são compradas.
- **Cadeia de produção**: minério/petróleo → refinado → componente →
  dispositivo → supercomputador. A cadeia-emblema continua além do v0:
  supercomputador → ... → **computador quântico**, a corrida de fundo
  deste mundo (declarada aqui; elos finais entram em versões futuras).
- **Ferramentas simuladas com custo realista**: InstaSim (CPM ~US$ 9/mil,
  eleva a demanda da empresa) e ZapSim (custo por conversa, eleva a
  conversão). Dinheiro de verdade dentro do mundo, efeito mensurável.
- **A Crônica**: cada evento relevante vira história datada — fundações,
  sondagens, marcos de cadeia, campanhas, falências, aquisições, atos de
  Deus. A crônica é o show; o placar é o campeonato.
- **Deus**: seed, nº de empresas e eventos injetáveis (choque de preço,
  descoberta, sanção) por config/CLI.

## As eras do mundo

A história deste mundo é uma corrida por uma árvore de produção, e ela
se organiza em eras nomeadas pelo fundador:

- **Era 1 — The Path to the Supercomputer**: a corrida pelo
  supercomputador. É a era implementada no v0: minério/petróleo →
  refinado → componente → dispositivo → supercomputador. Quem fecha a
  Era 1 prova que uma empresa autônoma consegue industrializar um planeta
  começando de uma picareta.
- **Era 2 — Path to Quantum**: a corrida pelo computador quântico — e o
  nome do projeto inteiro, porque é ela a corrida de fundo. Os elos além
  do supercomputador (semicondutores avançados, criogenia, materiais
  exóticos) entram em versões futuras; desde já, é a Era 2 que dá
  sentido à Era 1: ninguém corre pelo supercomputador, corre pelo que
  vem depois dele.

## Arquitetura

`src/mundo/`: `world.py` (mapa/dados reais) · `chain.py` (árvore de
produção, preços, instalações) · `companies.py` (agentes/personalidades) ·
`tools_sim.py` (InstaSim/ZapSim) · `engine.py` (ticks, mercado, ledger de
conservação) · `chronicle.py` (eventos/história) · `cli.py` (o painel de
Deus). `viewer/index.html`: player dos frames (mapa, placar, crônica).
Desenho completo do sistema em `docs/SDD.md`.

## Regra de computação

Código e testes estruturais na máquina de desenvolvimento; **a corrida de
verdade (120+ ticks) roda em notebook no Kaggle**
(`notebooks/kaggle_mundo_v0.ipynb`), que imprime o veredito e salva
frames/chronicle para o viewer.
