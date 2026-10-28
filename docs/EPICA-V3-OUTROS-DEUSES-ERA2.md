# Épica v3 — Outros deuses e Era 2: decomposição (registro de horizonte)

**Origem:** issue #17 (`[épica] v3 — Outros deuses e Era 2 (horizonte, só registro)`), que por sua vez aponta o PRD §10.
**Natureza deste documento:** decomposição para a fila *enxergar o destino* — exatamente a função que a issue declara. **Nada aqui é fatia aprovada, nada aqui vira issue nova.** A fila enxuta do fundador (27/10/2026) vale: (1) veredito válido da forja (#6), (2) merges decididos por ele, (3) próxima fatia de produto só depois do veredito.
**Convenção de leitura:** citações marcadas como *(PRD §n)* ou *(issue #17)* são texto do fundador/projeto. Tudo o mais é destilação; onde eu extrapolo além do texto, está marcado **[inferência]**.

---

## (a) O que a épica significa

### Outros deuses

Texto do PRD §2: *"Depois (v3): outros deuses — terceiros criam mundos, soltando suas próprias empresas e políticas para disputar temporadas e ligas."*

E do PRD §10 (v3): *"Terceiros criam mundos (editor de mundo: mapa, depósitos, eras) e soltam empresas próprias; ligas entre mundos e políticas."*

Destilando: hoje existe um Deus só — o fundador. Ele monta a Terra (seed, empresas, depósitos, choques), aperta "rodar" e assiste à Crônica (PRD §3). A v3 **multiplica o papel de Deus**: outra pessoa monta o *próprio* mundo (mapa, depósitos, eras), solta as *próprias* empresas — e, pelo §2, também as próprias **políticas** — e mundos diferentes passam a se encontrar em **temporadas e ligas**. O produto deixa de ser "o mundo do fundador" e vira "o lugar onde mundos de deuses diferentes disputam".

**Critério de sucesso da épica** *(PRD §10, reproduzido na issue #17)*: *"a primeira história emergente que o fundador assista sem ter criado o mundo nem as empresas."* É um critério de espectador, não de engenharia: a épica cumpre quando o fundador volta a ser público de uma história que não desenhou.

### Era 2

Texto do PRD §4: *"Era 2 — Path to Quantum: do supercomputador em diante — semicondutores avançados, criogenia, materiais exóticos — até o computador quântico, a cadeia-emblema e a corrida de fundo que dá nome ao projeto. Os elos finais entram em versões futuras; a Era 2 é o horizonte que organiza todas as decisões de balanceamento da Era 1."*

E a issue #17: *"a Era 2 (Path to Quantum) abre com os elos finais da cadeia até o computador quântico."*

Destilando: a Era 1 (implementada) termina no supercomputador. A Era 2 é a **continuação da mesma corrida** — novos elos de cadeia (semicondutores avançados, criogenia, materiais exóticos) que partem do supercomputador e terminam no computador quântico. Ela já cumpre um papel hoje sem existir: é o horizonte que impede a Era 1 de ser balanceada como um beco sem saída (PRD §11 lista "cadeia curta demais → a Era 1 acaba antes da história" como risco mitigado por "a Era 2 como horizonte desde já no balanceamento").

### O portão que a própria épica declara

A issue #17 é explícita: *"não fatiar nem implementar nada dela antes de v1 e v2 cumprirem seus critérios."* E declara a única consequência prática imediata: *"o editor de mundo do v3 pede que mundos sejam dados declarativos desde já — o que a issue C já respeita."* Ou seja: da épica inteira, só uma coisa incide sobre o trabalho de hoje — **mundos como dados declarativos** — e essa já é respeitada (o mundo vive em `data/world_data.json`, não em código).

Para situar os critérios de v1/v2 *(PRD §10)*:

- **v1** (um mundo maior e uma crônica rica): critério = *"uma corrida de 10 anos que o fundador assista até o fim sem tocar no celular — e queira rodar a próxima com outra seed."* Estado em 28/10/2026: crônica rica e viewer foram entregues e as issues #12/#13 foram fechadas como entregues; os recortes novos de mapa (#11) e as ferramentas novas (#14) foram **cortados pelo fundador** em 27/10/2026 ao enxugar a fila. Se o critério formal da v1 está cumprido ou dispensado é uma das perguntas abertas da seção (d) — este documento não decide isso.
- **v2** (empresas que aprendem; temporadas): critério = *"uma política aprendida vence (ou perde de forma interessante) — e a crônica consegue explicar a diferença de comportamento dela para as heurísticas."* Estado: é o Degrau 2 em curso — a forja de políticas-código (épica #1) com a corrida #6 atrás do primeiro veredito válido (V9 em lançamento). O critério da v2, portanto, **ainda não foi cumprido**.

---

## (b) Frentes candidatas

Estimativas são ordens de grandeza grosseiras (dias/semanas de trabalho focado), só para comparar frentes entre si — não são prazos.

### F1 — Formato de mundo declarativo (a fundação)

- **Objetivo:** um formato único e versionado de "mundo como dado": recorte/mapa, depósitos, cidades, commodities, eras e elenco inicial de empresas — validável por esquema, carregável pelo motor sem código novo. É a pré-condição de tudo o que a épica promete (um terceiro só cria mundo se mundo for um *arquivo*).
- **Dependências duras:** nenhuma técnica nova — o mundo atual já vive em `data/world_data.json` e a issue #17 registra que o desenho atual já respeita a restrição. O que falta é formalizar: esquema, validador e estabilidade do formato.
- **Custo:** baixo (dias).
- **Risco:** baixo. O risco real é formalizar cedo demais e congelar um formato que a Era 2 (F5) depois precise quebrar — mitigação: campo de versão desde o primeiro dia.

### F2 — Editor de mundo (a ferramenta do outro deus)

- **Objetivo:** a interface em que um terceiro monta o próprio mundo sobre o formato da F1 — escolher recorte, posicionar/ajustar depósitos e cidades, definir eras e elenco —, pré-visualiza no mapa e exporta o mundo como dado compartilhável.
- **Dependências duras:** F1 fechada (formato estável); a pilha de mapa já decidida e entregue no viewer-next (ADR-001: d3-geo + Canvas 2D) — o editor é, em grande parte, o mapa atual virado do avesso (de leitura para autoria) **[inferência]**.
- **Custo:** médio (semanas).
- **Risco:** médio — escopo. Um editor "completo" vira um game maker e engole o projeto; o corte certo é editar *dados do mundo*, não criar mecânicas.

### F3 — Empresas e políticas de terceiros (o elenco alheio)

- **Objetivo:** um terceiro solta as próprias empresas — personalidades/genomas — e as próprias **políticas-código**, que rodam sob a guarda v2 (Observation tipada + guarda AST) com o fog-of-war garantido por construção.
- **Dependências duras:** guarda v2 (entregue, mergeada); **veredito da forja (#6)** — é ele que prova (ou não) que políticas-código são um formato seguro, comparável e interessante de disputar; o empacotamento de política que a forja já usa (PolicySpec/programa) como formato de submissão **[inferência: o PRD não nomeia o formato]**.
- **Custo:** médio-alto (semanas).
- **Risco:** alto — é a frente onde "terceiros" morde: código alheio é superfície de trapaça e de quebra. A guarda é o produto aqui; qualquer atalho nela contamina todas as ligas da F4.

### F4 — Temporadas e ligas entre mundos

- **Objetivo:** o formato competitivo da v3: temporadas com regras fixas e placar, e ligas em que políticas/mundos de deuses diferentes se enfrentam (as mesmas políticas em mundos diferentes; mundos diferentes sob as mesmas regras).
- **Dependências duras:** F1 + F3; **as temporadas da v2 existindo primeiro com políticas próprias** (PRD §10/v2 introduz temporadas antes das ligas — a liga é a temporada com elenco alheio **[destilação do PRD §10]**); alguma forma de persistência de temporadas/placares **[inferência: o PRD fala em "placar público" na v2 sem definir infraestrutura]**.
- **Custo:** alto (é a frente-plataforma da épica).
- **Risco:** alto — decisões de infraestrutura (onde temporadas vivem, identidade de deuses, placar público) são decisões de produto/empresa, não de código; e "público" esbarra nos portões do fundador (exposição, IP, custo).

### F5 — Era 2: os elos finais da cadeia

- **Objetivo:** implementar a cadeia pós-supercomputador — semicondutores avançados, criogenia, materiais exóticos → computador quântico — com depósitos/commodities reais novos e balanceamento para a corrida continuar interessante depois que a Era 1 coroa um vencedor.
- **Dependências duras:** a Era 1 provada em corridas completas (é dela que sai o caixa/tecnologia que alimenta a Era 2 **[inferência de desenho a partir do PRD §4: "do supercomputador em diante"]**); dados reais dos novos elos no mesmo espírito da Era 1 (geografia/economia de verdade como level design, PRD §4); a cadeia como dado — os elos atuais já são tabelas, o que torna esta frente mais conteúdo+balanceamento que motor **[inferência a partir da arquitetura atual]**.
- **Custo:** médio (semanas, dominado por balanceamento, não por código).
- **Risco:** médio — balanceamento nos dois sentidos do PRD §11: cadeia longa demais e a história morre antes da Era 2; curta demais e o quântico vira trámite.

### F6 — A primeira história alheia (o veredito da épica)

- **Objetivo:** executar o critério de sucesso: um mundo e um elenco **não criados pelo fundador** rodam uma corrida completa, e ele assiste à Crônica como espectador. Quem cria pode ser um terceiro real ou, como ensaio, um agente/processo que não seja ele **[inferência — o PRD não define quem é o primeiro terceiro]**.
- **Dependências duras:** F2 + F3 (sem editor e sem elenco alheio, não há história alheia); a Crônica precisa narrar um mundo que ninguém da casa desenhou — a crônica rica atual já narra a partir de eventos+frames, sem conhecimento do desenho **[inferência a partir da implementação]**.
- **Custo:** baixo (uma corrida + a sessão de assistir), depois que F2/F3 existem.
- **Risco:** é um veredito, não uma construção — o risco é ele reprovar (história morna com elenco alheio) e devolver a épica para F2/F3/F5.

---

## (c) Portões de entrada

**Portão-mestre (da própria issue #17, inegociável):** nada desta épica é fatiado nem implementado antes de v1 e v2 cumprirem seus critérios — e, pela fila enxuta vigente, **nada começa antes do veredito válido da forja (#6) e da chamada expressa do fundador**. Esta decomposição é o máximo que a épica pede hoje.

| Frente | Destrava quando | Nunca começa antes de |
|---|---|---|
| F1 — Formato declarativo | Já está destravada como *restrição de desenho* (e respeitada); a formalização entra quando F2 ou F3 for agendada | — (é fundação, não fatia de v3) |
| F2 — Editor de mundo | F1 formalizada + chamada do fundador | Veredito da forja + critérios de v1/v2 resolvidos (seção d, pergunta 1) |
| F3 — Empresas/políticas de terceiros | Formato de política provado pela forja | **Veredito da forja (#6)** — sem ele, não se sabe se política-código é o formato |
| F4 — Ligas | Temporadas da v2 rodando com elenco próprio + F3 | Decisão do fundador sobre infraestrutura/exposição (pergunta 2) |
| F5 — Era 2 | Era 1 saudável em corridas completas + dados dos elos novos | Veredito da forja (regra 3 da fila enxuta) + chamada do fundador |
| F6 — Primeira história alheia | F2 + F3 prontas | As duas frentes existirem — é veredito, não construção |

Portões permanentes do fundador que atravessam a épica inteira: dinheiro/custo de infraestrutura, IP/exclusividade e exposição pública **não** são decididos em nenhuma frente sem ele (relevante sobretudo para F4).

---

## (d) Perguntas abertas — só o fundador responde

1. **A v1 está cumprida ou dispensada?** Você cortou os recortes novos e as ferramentas novas da v1 ao enxugar a fila; crônica e viewer entraram. O critério formal da v1 (assistir uma corrida de 10 anos até o fim e querer a próxima) conta como cumprido, dispensado, ou ainda falta alguma coisa nomeável?
2. **"Terceiros" é quem, primeiro?** (a) só você, com mundos alternados; (b) convidados nomeados; (c) público aberto. A resposta muda F2/F4 de ferramenta local para plataforma — e muda custo e exposição.
3. **Política de terceiro é código ou genoma?** A forja aposta em código sob a guarda v2 (mais expressivo, mais risco); o torneio usa genoma de parâmetros (mais seguro, mais pobre). A F3 herda a resposta — ou convive com os dois formatos?
4. **A Era 2 continua no mesmo mundo** (a corrida segue depois do primeiro supercomputador, como o PRD §4 sugere com "do supercomputador em diante") **ou abre como temporada/mundo separado?**
5. **Liga v0 pode ser troca de arquivos** (mundo/política como arquivo que se compartilha e roda local) **ou liga já nasce precisando de servidor/placar central?** A primeira opção mantém a F4 barata e offline; a segunda é decisão de empresa.

---

## (e) Relação com a fila enxuta atual

A fila vigente (decisão do fundador, 27/10/2026): **(1) veredito válido da forja (V9, issue #6) → (2) merges que ele ordenar → (3) próxima fatia de produto só depois do veredito.**

A épica #17 senta **atrás da #6, no horizonte** — é o destino que a fila enxerga, não um item dela. Das seis frentes, nenhuma disputa prioridade com a forja; duas dependem diretamente do veredito dela (F3 e, pela regra 3 da fila, F5). A única incidência presente da épica é a que ela mesma declara: mundos como dados declarativos — respeitada hoje e a ser preservada em qualquer fatia de v1/v2 que toque o formato do mundo (é esse o uso prático deste documento até a épica ser chamada).

Quando o fundador chamar a v3, este documento é a matéria-prima da fatiagem — **naquela ocasião**, com as respostas da seção (d) na mesa.
