# PRD — PATH TO QUANTUM
### O mundo onde empresas autônomas nascem, competem e fecham a cadeia
### v1.0 · 26/10/2026

> Régua deste documento, na voz do fundador: **a primeira coisa é se divertir
> construindo; impacto mundial ou nada; sem desespero por grana.** Se uma
> decisão de produto contradiz a diversão de criar e assistir a este mundo,
> ela está errada — não importa quão boa ela pareça numa planilha.

---

## 1. O produto em uma frase

**Path to Quantum é um mundo vivo: a Terra de verdade, com recursos e
unidades reais, habitada por empresas autônomas de IA que extraem, produzem,
vendem e competem para fechar cadeias de produção inteiras — e um Deus (o
jogador-criador) que constrói o mundo, solta as empresas e assiste à história
emergir.**

Não é planilha, não é dashboard, não é consultoria. É um mundo que roda,
gera história e prende quem assiste — o primo industrial de Victoria II e
Stellaris, onde os atores são empresas e o mapa é o planeta real.

## 2. Quem usa

- **O Deus (usuário primário)**: o criador do mundo. Configura a Terra
  (seed, empresas, eventos), aperta "rodar" e lê a história que sai do outro
  lado. Ele não joga *como* uma empresa; ele é a força da natureza e do
  mercado.
- **As empresas (os habitantes)**: agentes autônomos com nome, sede,
  personalidade e ambição. São elas que vivem o mundo — o produto existe
  para que a vida delas seja interessante de assistir.
- **Depois (v3)**: outros deuses — terceiros criam mundos, soltando suas
  próprias empresas e políticas para disputar temporadas e ligas.

## 3. A experiência do Deus

O loop central do produto tem três tempos:

1. **Criar** — o Deus monta o mundo: qual recorte da Terra, quantas
   empresas, com que caixa e que personalidades, que depósitos existem,
   que choques vão acontecer (e quando). Criar o mundo já é metade do jogo:
   cada configuração é uma história diferente esperando para acontecer.
2. **Soltar** — o tempo começa a correr (ticks mensais). As empresas sondam
   no escuro, reivindicam território, abrem minas, refinam, fabricam,
   anunciam, vendem, compram umas das outras, quebram e são compradas.
   O Deus pode intervir com **atos de Deus**: choque de preço, descoberta
   de um depósito novo, sanção comercial — a mão invisível com nome e data.
3. **Assistir** — a história chega como **Crônica**: um feed narrado e
   datado ("[mar/2029] Lítio Austral sonda o Salar de Uyuni e encontra um
   depósito RICO"), acompanhado do mapa mudando de dono e do placar do
   campeonato. Assistir é o produto: replay com play/pause/velocidade,
   scrub pela linha do tempo, e o veredito final de cada corrida — quem
   liderou em caixa, quem subiu mais alto na cadeia, quantos
   supercomputadores o mundo entregou.

**Critério de diversão (inegociável):** toda corrida tem que produzir
história que valha ser contada — rivalidade, virada, falência, monopólio,
corrida de fundo pelo próximo elo. Se 120 ticks geram uma tabela morna e
nenhuma história, o defeito é do mundo, não do espectador.

## 4. O mundo

- **A Terra de verdade.** Geografia real, depósitos reais em posições reais
  (Atacama, Uyuni, Escondida, Carajás, pré-sal, Vaca Muerta...), cidades
  reais como mercados, unidades reais: toneladas, unidades, US$. A
  realidade é o level design — ela já vem balanceada por 4,5 bilhões de
  anos de geologia e pela economia de verdade.
- **Fog-of-war do subsolo.** Onde os depósitos estão, todo mundo sabe;
  quanto têm e com que teor, só quem **sondou**. Informação é um ativo
  conquistado furando — nunca um dado dado.
- **As eras da cadeia.** A história do mundo se organiza como uma corrida
  por uma árvore de produção, em eras nomeadas:
  - **Era 1 — The Path to the Supercomputer**: minério/petróleo → refinado
    → componente → dispositivo → **supercomputador**. A era implementada
    no v0: a primeira era da industrialização autônoma.
  - **Era 2 — Path to Quantum**: do supercomputador em diante —
    semicondutores avançados, criogenia, materiais exóticos — até o
    **computador quântico**, a cadeia-emblema e a corrida de fundo que dá
    nome ao projeto. Os elos finais entram em versões futuras; a Era 2 é o
    horizonte que organiza todas as decisões de balanceamento da Era 1.

## 5. As empresas

- **Personalidade antes de inteligência.** Cada empresa nasce com traços —
  agressividade, apetite a risco, obsessão por verticalizar, propensão a
  marketing — que fazem empresas com a mesma "inteligência" viverem vidas
  completamente diferentes. A Agressiva expande e quebra; a
  Verticalizadora sobe a cadeia em silêncio; a Marqueteira vende o que não
  tem. Personalidade é o que transforma simulação em elenco.
- **Autonomia crescente (a escada):**
  1. **Heurísticas com personalidade (v0)** — políticas parametrizadas
     pelos traços. Determinísticas, baratas, legíveis na crônica.
  2. **Políticas aprendidas (v2)** — empresas cuja política é treinada
     (RL/aprendizado no Kaggle) disputam temporadas contra heurísticas e
     entre si. O mundo vira o ginásio onde estratégias econômicas são
     selecionadas como espécies.
  3. **CEOs LLM fora do tick (futuro)** — um modelo de linguagem como
     "CEO" que decide em fronteiras estratégicas (a cada ano simulado:
     pivotar, fundir, declarar guerra de preços) — **nunca dentro do
     tick**, para o motor continuar determinístico, rápido e auditável.
- **Vida completa**: fundação → expansão → maturidade → falência ou
  aquisição. Empresa morta não some: seus ativos mudam de dono e a crônica
  lembra quem ela foi.

## 6. As ferramentas simuladas — a camada de serviços do mundo

O mundo não simula só a física: simula também **a camada de ferramentas
digitais que as empresas reais usam** — com as mecânicas e os custos das
de verdade, mas 100% dentro da simulação:

- **InstaSim** (rede social): campanhas a CPM realista (~US$ 9/mil
  impressões) que elevam a demanda pelos produtos da empresa por alguns
  meses.
- **ZapSim** (mensageria): canal de vendas a custo por conversa (faixa
  real de API de mensagens) que eleva a conversão enquanto ativo.

Regras da camada:

- **Cada ferramenta é um módulo plugável** com custo, duração e efeito
  mensurável no ledger. Nova "integração" = novo módulo, sem tocar no
  motor: estúdio de vídeo simulado, marketplace simulado, banco simulado
  (crédito/juros), logística simulada (frete/porto), busca/ads simulados.
- **Custo realista é lei**: se a ferramenta real custa X por milhar, a
  simulada custa na mesma faixa. A economia do mundo só é crível se os
  preços forem os do mundo real.
- Empresas **escolhem** usar (ou não) conforme a personalidade — a
  ferramenta é uma decisão econômica, não um botão mágico.

## 7. A Crônica é o show

- A crônica não é um log de debug: é a **mídia do mundo**. Eventos
  estruturados (fundação, sondagem, marco de cadeia, campanha, falência,
  aquisição, ato de Deus, recorde) renderizados como narrativa datada.
- Formatos que a crônica alimenta: o feed ao vivo durante a corrida, o
  replay no viewer, o veredito impresso ao fim de cada corrida e — no
  horizonte — temporadas publicadas: "a história do mundo nº 7" como
  conteúdo que se compartilha.
- O **placar** (caixa, elo da cadeia, instalações, viva/falida) é o
  campeonato que dá tensão à narrativa; a crônica é o porquê de alguém
  se importar com o placar.

## 8. A tese de longo prazo

Se o futuro é a IA fechando cadeias de produção inteiras sozinha — sem
alguém otimizando-a por fora —, esse futuro precisa de um lugar para
nascer, errar e ser selecionado. **Este mundo é esse lugar: a academia
das economias autônomas.** Cada corrida é um experimento de história
econômica alternativa; cada temporada, uma geração de empresas mais
capazes que a anterior. Quem constrói o mundo onde agentes econômicos
aprendem constrói a infraestrutura da era das empresas autônomas — e, de
quebra, o jogo de grand strategy que não existia.

## 9. O que este produto NÃO é (anti-escopo permanente)

- Não é consultoria, nem vende horas, relatórios ou "benchmark anual".
- Não é uma API em busca de quem nunca abre o produto; integrações
  externas servem ao mundo, nunca o contrário.
- Não é um simulador "sério" que pede desculpas por ser divertido:
  emergência, rivalidade e história vêm antes de realismo burocrático.
- Não é um jogo de um jogador só contra o mapa: o coração são **empresas
  contra empresas**, com o Deus acima de todas.

## 10. MVPs como saltos

### v0 — O Nascimento *(feito)*
América do Sul real, 10 depósitos, 8 cidades, 8 empresas heurísticas,
cadeia até o supercomputador, InstaSim/ZapSim, crônica, viewer de replay,
corrida de 10 anos no Kaggle. **Critério cumprido:** a história emerge —
no smoke de 2 anos já houve sondagem rica, corrida pela cadeia, queima de
caixa e liderança trocando de mãos.

### v1 — Um mundo maior e uma crônica rica
- Mais Terra: novos recortes (América do Norte, África, Ásia) e dezenas
  de depósitos/cidades; mais commodities e elos intermediários da Era 1.
- Replay completo: viewer com scrub fino, câmera nos marcos da crônica,
  comparador de corridas (mesma seed, Deuses diferentes).
- Mais ferramentas: estúdio de vídeo simulado e marketplace simulado
  entram como módulos; empresas anunciam em vídeo e vendem em prateleira
  disputada.
- Crônica rica: rivalidades detectadas (quem comprou de quem, guerras de
  preço), retrospectiva automática da corrida ("a década em que...").
- **Critério de sucesso:** uma corrida de 10 anos que o fundador assista
  até o fim sem tocar no celular — e queira rodar a próxima com outra seed.

### v2 — Empresas que aprendem (temporadas)
- Políticas plugáveis entram em produção: a primeira política treinada
  por RL no Kaggle disputa uma temporada inteira contra as heurísticas.
- Temporadas como formato: regras fixas por temporada, placar público,
  políticas versionadas como "espécies" que evoluem entre temporadas.
- Protótipo de CEO LLM fora do tick decidindo nas viradas de ano.
- **Critério de sucesso:** uma política aprendida vence (ou perde de forma
  interessante) — e a crônica consegue *explicar* a diferença de
  comportamento dela para as heurísticas.

### v3 — Outros deuses
- Terceiros criam mundos (editor de mundo: mapa, depósitos, eras) e
  soltando empresas próprias; ligas entre mundos e políticas.
- A Era 2 (Path to Quantum) abre com os elos finais da cadeia até o
  computador quântico.
- **Critério de sucesso:** a primeira história emergente que o fundador
  assista sem ter criado o mundo nem as empresas.

## 11. Riscos (honestos)

- **Empresas burras demais** → história morna. Mitigação: personalidade
  forte primeiro, inteligência depois; balancear pelo critério de
  diversão da crônica, não por "realismo".
- **Mundo pequeno demais** → corridas se repetem. Mitigação: a Terra é
  grande e barata de adicionar — conteúdo é dado real, não level design.
- **Cadeia curta demais** → a Era 1 acaba antes da história. Mitigação:
  elos intermediários e a Era 2 como horizonte desde já no balanceamento.
- **O Deus espectador cansa** → Mitigação: atos de Deus, temporadas e
  políticas de terceiros (v2/v3) renovam o elenco sem mudar o motor.

## 12. Como medimos se está funcionando

- Marcos por corrida (marcos de cadeia, falências, aquisições, atos de
  Deus) — corrida sem marcos é corrida defeituosa.
- Quantas empresas chegam a cada elo por corrida (a pirâmide da cadeia).
- Supercomputadores entregues por década simulada (o "placar da Era 1").
- Tempo assistido no replay e corridas por seed (o Deus volta?).
- E a métrica que manda em todas: **o fundador perdeu a noção do tempo
  assistindo?** Se sim, o produto está certo; o resto é consequência.
