# Fronteira 2026 — estudo de 26/10/2026 (síntese; relatório completo na conversa)

## As três mudanças de 2024→2026
1. **O gargalo de MARL era velocidade do ambiente — e caiu.** EconoJax (arXiv:2410.22165): a economia do AI Economist reescrita em JAX treina 100 agentes em ~13 min (antes: dias). JaxMARL-BC (arXiv:2610.28907, out/2026): calibração macro DSGE de >1 mês → ~2 h. PowerMarketJax: 33× CPU, 1.024 mercados paralelos.
2. **A unidade de evolução virou PROGRAMA.** AlphaEvolve (arXiv:2506.13131) evolui código inteiro com LLM-mutador + avaliador; ecossistema aberto pronto: OpenEvolve 0.4.0, ShinkaEvolve (arXiv:2509.19349, 150 amostras bastam), CodeEvolve (arXiv:2510.14150) superando o AlphaEvolve com Qwen3-Coder-30B open-weight a ~10× menos custo. DGM (Sakana) mostra o risco: reward hacking do avaliador — anti-trapaça desde o dia 1.
3. **Sociedades LLM viraram gênero, com lição consolidada:** Project Sid (1.000+ agentes), AgentSociety (10 mil, arXiv:2502.08691), SwarmWorld (MIT, arXiv:2608.26081 — sociedades open-weight em 4× RTX 3090) — LLM NÃO aguenta o tick; brilha em fronteira rara (estratégia/cultura). Valida o CEO anual do SDD.

## Escada de complexidade
- **Degrau 1 — motor GPU + mundo vivo:** tick vetorizado em JAX (funções puras sobre arrays), milhares de mundos em batch; orçamento liberado compra equipamentos/país/ciclos reais e campos de 100 empresas. Custo de implementação ALTO, visibilidade baixa — é multiplicador, não salto.
- **Degrau 2 — políticas viram CÓDIGO evoluído por LLM** ⭐: genótipo = o arquivo da política; loop tipo OpenEvolve/ShinkaEvolve com o torneio pré-registrado como avaliador; MAP-Elites por comportamento; mutador Qwen3-Coder-30B + DeepSeek em profundidade. LLM só ENTRE temporadas; temporada roda código congelado e determinístico. Espectador vê estratégias com assinatura, código legível, linhagens.
- **Degrau 3 — CEOs com nome, memória e cultura:** CEO LLM open-weight anual (pesos públicos = decisão congelável/auditável), memória da própria Crônica, diplomacia estruturada entre empresas (propostas, ameaças, cartéis). Depois do 2 provado.

## Recomendação
**Próximo salto = Degrau 2**, com o Degrau 1 só na versão mínima necessária. Experimento: **ptq-policy-forge-v1** (Kaggle) — semente = HeuristicPolicy atual; ~300 candidatos em cascata (8 episódios → 64 nos finalistas); avaliação cega nos blocos travados do torneio vs. v0, campeão CMA-ES e campeão IPPO; vereditos PROVA (ΔS≥+0,08, IC>0, portões ok) / MATA (→ investimento vai ao Degrau 1) / PARCIAL (evolução por arquétipo). Entregável de leitura: os 5 melhores programas com diff comentado — se não forem interessantes de LER, o degrau falhou no critério do produto.
Aproveitável já: dataset Kaggle `ramjasmaurya/mineraloresaroundtheworld` (304.632 minas, 166 países) para expandir o mundo; formato Kaggle Simulations/Lux AI como template do futuro modo "outros deuses".
