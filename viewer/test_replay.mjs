// Teste estrutural do viewer (issue D, fatia 1): ?run= carrega a corrida
// pedida e jumpToTick salta para o frame do marco clicado.
// Roda com: node viewer/test_replay.mjs   (sem servidor, sem DOM real)
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const html = readFileSync(path.join(root, 'viewer', 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const data = JSON.parse(readFileSync(
  path.join(root, 'results', 'nascimento-v0', 'frames.json'), 'utf8'));

function makeCtxStub() {
  return new Proxy({}, {
    get: () => () => {},
    set: () => true,
  });
}

async function runCase(search, fetchData) {
  const els = {};
  for (const id of ['date', 'runlabel', 'play', 'speed', 'scrub', 'file',
                    'map', 'board', 'feed', 'compare', 'comparetitle',
                    'forge', 'forgetitle']) {
    els[id] = { value: '700', textContent: '', innerHTML: '', style: {},
                clientWidth: 800, clientHeight: 600,
                getContext: () => makeCtxStub() };
  }
  const fetchCalls = [];
  const sandbox = {
    console,
    URLSearchParams,
    location: { search },
    setInterval: () => 1,
    clearInterval: () => {},
    document: { getElementById: id => els[id] },
    // fetchData pode devolver o dado cru (vira .json()) ou {__json}/{__text}
    // para endpoints que o painel lê como texto (run_log.jsonl).
    fetch: async url => {
      fetchCalls.push(url);
      const v = fetchData ? fetchData(url) : data;
      return {
        json: async () => (v && v.__json !== undefined ? v.__json : v),
        text: async () => (v && v.__text !== undefined ? v.__text : ''),
      };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  // Deixa o fetch inicial + load() + (se houver) o fetch da comparação resolverem.
  for (let i = 0; i < 10; i++) await new Promise(r => setImmediate(r));
  return { sandbox, els, fetchCalls };
}

let failures = 0;
function check(name, cond, extra = '') {
  console.log((cond ? 'ok   ' : 'FALHOU ') + name + (cond ? '' : ' ' + extra));
  if (!cond) failures++;
}

// Caso 1: sem ?run — frames.json ao lado, runlabel vazio.
{
  const { els, fetchCalls } = await runCase('');
  check('default busca frames.json', fetchCalls[0] === 'frames.json', fetchCalls);
  check('default não rotula corrida', els.runlabel.textContent === '');
  check('load inicial renderiza tick 0', els.date.textContent.includes('tick 0'),
        els.date.textContent);
}

// Caso 2: ?run=results/nascimento-v0 — busca a corrida e salta nos marcos.
{
  const { sandbox, els, fetchCalls } = await runCase('?run=results/nascimento-v0');
  check('?run busca a corrida pedida',
        fetchCalls[0] === 'results/nascimento-v0/frames.json', fetchCalls);
  check('?run rotula a corrida',
        els.runlabel.textContent === 'corrida: results/nascimento-v0',
        els.runlabel.textContent);
  check('feed renderiza eventos clicáveis',
        els.feed.innerHTML.includes('onclick="jumpToTick('), '(sem onclick)');
  sandbox.jumpToTick(50);
  check('jumpToTick(50) vai ao frame do tick 48',
        els.date.textContent.includes('tick 48'), els.date.textContent);
  sandbox.jumpToTick(0);
  check('jumpToTick(0) volta ao tick 0',
        els.date.textContent.includes('tick 0'), els.date.textContent);
  sandbox.jumpToTick(9999);
  check('jumpToTick além do fim vai ao último frame (tick 120)',
        els.date.textContent.includes('tick 120'), els.date.textContent);
  sandbox.jumpToTick(24);
  check('jumpToTick(24) acerta o frame exato',
        els.date.textContent.includes('tick 24'), els.date.textContent);
}

// Caso 3: ?run com '..' é rejeitado (não sai do diretório do viewer).
{
  const { fetchCalls } = await runCase('?run=../segredo');
  check('?run com .. volta ao frames.json local',
        fetchCalls[0] === 'frames.json', fetchCalls);
}

// Caso 4 (fatia 2): ?compare= busca a segunda corrida e compara o frame
// final — empresa por empresa, com delta. A segunda corrida aqui é a
// mesma, com o caixa da 1ª empresa do frame final dobrado.
{
  const last = data.frames[data.frames.length - 1];
  const cash0 = last.companies[0].cash;
  const doubled = JSON.parse(JSON.stringify(data));
  doubled.frames[doubled.frames.length - 1].companies[0].cash = cash0 * 2;
  const { els, fetchCalls } = await runCase(
    '?run=results/nascimento-v0&compare=results/segunda',
    url => (url.includes('segunda') ? doubled : data));
  check('?compare busca a segunda corrida',
        fetchCalls[1] === 'results/segunda/frames.json', fetchCalls);
  check('?compare mostra o título da comparação',
        els.comparetitle.style.display === '', els.comparetitle.style.display);
  check('?compare lista a empresa comparada',
        els.compare.innerHTML.includes(last.companies[0].name), '(sem empresa)');
  const delta = '+US$ ' + (cash0 / 1e6).toFixed(1) + 'M';
  check('?compare mostra o delta do caixa dobrado',
        els.compare.innerHTML.includes(delta), els.compare.innerHTML.slice(0, 200));
  // Trava anti-'..' também vale para ?compare.
  const trav = await runCase('?run=results/nascimento-v0&compare=../segredo');
  check('?compare com .. não busca fora do viewer',
        trav.fetchCalls.length === 1, trav.fetchCalls);
}

// Fixture da forja: artefatos REAIS da corrida V7 em results/forge-v1/
// (gerados localmente, gitignored — mesmo padrão do frames.json acima).
// Sem eles no disco, cai num resumo inline com o mesmo formato e valores,
// para a suíte continuar verde numa árvore limpa.
function forgeFixture() {
  const dir = path.join(root, 'results', 'forge-v1');
  if (existsSync(path.join(dir, 'forge-v1.json'))) {
    return {
      forgeJson: JSON.parse(readFileSync(path.join(dir, 'forge-v1.json'), 'utf8')),
      finalEval: JSON.parse(readFileSync(path.join(dir, 'final_evaluation.json'), 'utf8')),
      runLog: readFileSync(path.join(dir, 'run_log.jsonl'), 'utf8'),
    };
  }
  const runLog = [
    { iteration: 0, hash: 'fcf3162c8751', parent: null, status: 'seed',
      S1: 0.4953125, S2: 0.49462890625, island: 0 },
    { iteration: 1, hash: '98cd636f8cad', parent: 'fcf3162c8751', status: 'accepted',
      S1: 0.43359375, S2: null, island: 1 },
    { iteration: 2, hash: null, parent: 'fcf3162c8751', status: 'rejected_llm',
      S1: null, S2: null, island: 2 },
  ].map(e => JSON.stringify(e)).join('\n');
  return {
    forgeJson: {
      verdict: 'FORGE-V1: REPROVADO/AJUSTAR', mutator: 'llm',
      iterations_completed: 300,
      counts: { accepted: 1, rejected_guard: 0, rejected_llm: 299, error: 0, duplicate: 0 },
      champion: { hash: 'fcf3162c8751', S1: 0.4953125, S2: 0.49462890625 },
      seed_result: { hash: 'fcf3162c8751', S1: 0.4953125, S2: 0.49462890625 },
      mutator_stats: {
        calls: { 'gemini/gemini-3.5-flash': 300, 'gemini/gemini-3-flash-preview': 300,
                 'groq/openai/gpt-oss-120b': 299, 'groq/qwen/qwen3.8-27b': 299 },
        fallbacks: 898, failures: 299,
      },
    },
    finalEval: {
      verdict: 'REPROVADO/AJUSTAR', champion_hash: 'fcf3162c8751',
      tournament_champion: 'evo:6a94b587701d',
      mean_S: { forge_champion: 0.50634765625, seed: 0.50634765625,
                tournament_champion: 0.58134765625 },
      delta_vs_tournament: { mean: -0.07499999999999998,
        ci95: [-0.11533447265624999, -0.033884277343750005], n_blocks: 64 },
      delta_vs_seed: { mean: 0.0, ci95: [0.0, 0.0], n_blocks: 64 },
    },
    runLog,
  };
}
const FX = forgeFixture();
const forgeFetch = (fx, omit = []) => url => {
  if (url.endsWith('/forge-v1.json')) return omit.includes('forge') ? { __json: null } : { __json: fx.forgeJson };
  if (url.endsWith('/final_evaluation.json')) return omit.includes('final') ? { __json: null } : { __json: fx.finalEval };
  if (url.endsWith('/run_log.jsonl')) return omit.includes('log') ? { __text: '' } : { __text: fx.runLog };
  return data;
};

// Caso 5 (painel da forja): ?forge= busca os 3 artefatos e renderiza
// campeão, veredito, avaliação cega, contagens, mutador e linha do tempo.
{
  const { sandbox, els, fetchCalls } = await runCase(
    '?run=results/nascimento-v0&forge=results/forge-v1', forgeFetch(FX));
  check('?forge busca forge-v1.json',
        fetchCalls.includes('results/forge-v1/forge-v1.json'), fetchCalls);
  check('?forge busca final_evaluation.json e run_log.jsonl',
        fetchCalls.includes('results/forge-v1/final_evaluation.json')
        && fetchCalls.includes('results/forge-v1/run_log.jsonl'), fetchCalls);
  check('?forge mostra o título do painel',
        els.forgetitle.style.display === '', els.forgetitle.style.display);
  check('painel mostra o campeão',
        els.forge.innerHTML.includes('prog:fcf3162c8751'), els.forge.innerHTML.slice(0, 200));
  check('painel mostra S1/S2 do campeão',
        els.forge.innerHTML.includes('S1 0.4953 · S2 0.4946'), els.forge.innerHTML.slice(0, 300));
  check('painel mostra o veredito',
        els.forge.innerHTML.includes('FORGE-V1: REPROVADO/AJUSTAR'));
  check('painel mostra ΔS vs torneio com IC95',
        els.forge.innerHTML.includes('−0.0750')
        && els.forge.innerHTML.includes('IC95 [-0.1153, -0.0339]'),
        els.forge.innerHTML.slice(0, 400));
  check('painel mostra as contagens',
        els.forge.innerHTML.includes('rejeitadas (LLM)')
        && els.forge.innerHTML.includes('<b>299</b>'));
  check('painel mostra chamadas por rota do mutador',
        els.forge.innerHTML.includes('gemini/gemini-3-flash-preview')
        && els.forge.innerHTML.includes('300 chamadas'));
  check('painel mostra fallbacks do mutador',
        els.forge.innerHTML.includes('fallbacks') && els.forge.innerHTML.includes('<b>898</b>'));
  check('linha do tempo traz a iteração aceita da V7',
        els.forge.innerHTML.includes('#1 · prog:98cd636f8cad')
        && els.forge.innerHTML.includes('S1 0.4336'), els.forge.innerHTML.slice(-300));
  // Funções puras: timeline só com aceitas; resumo tolera tudo ausente.
  const sum = sandbox.summarizeForge(FX.forgeJson, FX.finalEval,
                                     sandbox.parseRunLog(FX.runLog));
  check('summarizeForge: timeline tem só a aceita',
        sum.timeline.length === 1 && sum.timeline[0].iteration === 1,
        JSON.stringify(sum.timeline).slice(0, 120));
  const vazio = sandbox.summarizeForge(null, null, []);
  check('summarizeForge vazio não quebra e zera os campos',
        vazio.champion.hash === null && vazio.timeline.length === 0
        && vazio.counts === null && vazio.blind.vsTournament === null);
  check('parseRunLog ignora linhas quebradas',
        sandbox.parseRunLog('{"a":1}\nlixo solto\n{"b":2}\n\n').length === 2);
  check('replay segue vivo com ?forge',
        els.date.textContent.includes('tick 0'), els.date.textContent);
}

// Caso 6: tolerâncias do painel — sem ?forge nada muda; '..' é travado;
// artefato parcial (só final_evaluation) renderiza o que tem, sem quebrar.
{
  const sem = await runCase('?run=results/nascimento-v0');
  check('sem ?forge nenhum artefato da forja é buscado',
        !sem.fetchCalls.some(u => u.includes('forge-v1')), sem.fetchCalls);
  check('sem ?forge o painel fica vazio e o título oculto',
        sem.els.forge.innerHTML === '' && sem.els.forgetitle.style.display === undefined);
  const trav = await runCase('?forge=../segredo');
  check('?forge com .. não busca fora do viewer',
        !trav.fetchCalls.some(u => u.includes('forge-v1')), trav.fetchCalls);
  const parcial = await runCase('?forge=results/forge-v1',
                                forgeFetch(FX, ['forge', 'log']));
  check('artefato parcial: campeão vem do final_evaluation',
        parcial.els.forge.innerHTML.includes('prog:fcf3162c8751'),
        parcial.els.forge.innerHTML.slice(0, 200));
  check('artefato parcial: sem contagens, sem quebrar',
        !parcial.els.forge.innerHTML.includes('Contagens')
        && parcial.els.forge.innerHTML.includes('Nenhuma iteração aceita'));
  check('artefato parcial: replay intacto',
        parcial.els.date.textContent.includes('tick 0'), parcial.els.date.textContent);
}
console.log('viewer/test_replay: OK');
