// Teste estrutural do viewer (issue D, fatia 1): ?run= carrega a corrida
// pedida e jumpToTick salta para o frame do marco clicado.
// Roda com: node viewer/test_replay.mjs   (sem servidor, sem DOM real)
import { readFileSync } from 'node:fs';
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

async function runCase(search) {
  const els = {};
  for (const id of ['date', 'runlabel', 'play', 'speed', 'scrub', 'file',
                    'map', 'board', 'feed']) {
    els[id] = { value: '700', textContent: '', innerHTML: '',
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
    fetch: async url => {
      fetchCalls.push(url);
      return { json: async () => data };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  // Deixa o fetch inicial + load() resolverem.
  for (let i = 0; i < 5; i++) await new Promise(r => setImmediate(r));
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

if (failures) { console.log(`${failures} falha(s)`); process.exit(1); }
console.log('viewer/test_replay: OK');
