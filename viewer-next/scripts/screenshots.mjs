// Screenshots de prova (SPEC §8.3) do viewer-next servido — F6.
// Uso:
//   npm run build -- --base=./ --outDir /tmp/ptq-shots-dist
//   node scripts/screenshots.mjs /tmp/ptq-shots-dist
// O script: cria fixtures LOCAIS dentro do dist temporário (segunda corrida p/
// ?compare= a partir de results/nascimento-v0; artefatos da forja com os
// valores reais da corrida V8) e dirige o Chromium headless via CDP (sem
// dependência nova), abrindo o dist por file:// com --allow-file-access-from
// -files — nesta VM o Chromium 152 bloqueia até navegação do próprio browser
// para 127.0.0.1 (ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS), e o file://
// com a flag lê os JSONs relativos sem servidor nenhum (o que também prova o
// VIS-13: artefato estático autocontido). Salta aos ticks via
// window.ptqJumpToTick e salva os PNGs em viewer-next/screenshots/.
import { spawn } from 'node:child_process';
import { copyFileSync, mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.dirname(here);
const dist = process.argv[2] || '/tmp/ptq-shots-dist';
const outDir = path.join(appRoot, 'screenshots');
mkdirSync(outDir, { recursive: true });

// --- fixtures (só no dist temporário; nada disto é versionado) ---------------
const fxRun = path.join(dist, 'fixtures', 'nascimento');
mkdirSync(fxRun, { recursive: true });
copyFileSync(path.join(appRoot, '..', 'results', 'nascimento-v0', 'frames.json'), path.join(fxRun, 'frames.json'));
const fxForge = path.join(dist, 'fixtures', 'forge-v1');
mkdirSync(fxForge, { recursive: true });
writeFileSync(path.join(fxForge, 'forge-v1.json'), JSON.stringify({
  champion: { hash: '038395fa93a1', S1: 0.4797, S2: 0.5175 },
  seed_result: { hash: 'seedhash', S1: 0.44, S2: 0.49 },
  verdict: 'FORGE-V1: REPROVADO/AJUSTAR',
  iterations_completed: 300,
  mutator: 'multi-rota',
  counts: { accepted: 4, rejected_llm: 295, rejected_guard: 0, error: 1, duplicate: 0 },
  mutator_stats: { calls: { nvidia: 300, groq: 295, gemini: 40 }, salvamentos: 4 },
}, null, 2));
writeFileSync(path.join(fxForge, 'final_evaluation.json'), JSON.stringify({
  tournament_champion: 'prog:deadbeef',
  mean_S: { forge_champion: 0.46, seed: 0.44, tournament_champion: 0.5153 },
  delta_vs_tournament: { mean: -0.0553, ci95: [-0.0998, -0.0112] },
  delta_vs_seed: { mean: 0.0197, ci95: [-0.01, 0.05] },
}, null, 2));
writeFileSync(path.join(fxForge, 'run_log.jsonl'), [
  '{"iteration": 1, "hash": "h1", "S1": 0.41, "island": "a", "status": "rejected_llm"}',
  '{"iteration": 3, "hash": "h3", "S1": 0.4797, "island": "b", "status": "accepted"}',
  '{"iteration": 7, "hash": "h7", "S1": 0.45, "island": "a", "status": "accepted"}',
].join('\n'));

// --- Chromium via CDP ----------------------------------------------------------
const chromeBin = process.env.CHROME_BIN || '/opt/meta-chromium/chrome';
const chrome = spawn(chromeBin, [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars',
  '--allow-file-access-from-files',
  '--remote-debugging-port=9223', '--user-data-dir=/tmp/ptq-cdp-profile', 'about:blank',
], { stdio: 'ignore' });
const baseUrl = `file://${dist}/index.html`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl = null;
for (let i = 0; i < 50 && !wsUrl; i++) {
  try {
    const list = await (await fetch('http://127.0.0.1:9223/json/list')).json();
    wsUrl = list.find((t) => t.type === 'page')?.webSocketDebuggerUrl;
  } catch { await sleep(200); }
}
if (!wsUrl) { console.error('CDP indisponível'); process.exit(1); }
const ws = new WebSocket(wsUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let seq = 0;
const pending = new Map();
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result); pending.delete(msg.id); }
});
const cdp = (method, params = {}) => new Promise((res) => { const id = ++seq; pending.set(id, res); ws.send(JSON.stringify({ id, method, params })); });
const evaluate = async (expr) => {
  const r = await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  return r?.result?.value;
};
async function waitFor(expr, timeout = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) { if (await evaluate(expr)) return true; await sleep(250); }
  throw new Error(`timeout esperando: ${expr}`);
}
async function shot(name, { width, height, mobile = false, url = baseUrl, ready, act }) {
  await cdp('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile });
  await cdp('Page.navigate', { url });
  await waitFor(ready);
  if (act) { await evaluate(act); await sleep(600); await evaluate(act); await sleep(150); }
  const r = await cdp('Page.captureScreenshot', { format: 'png' });
  writeFileSync(path.join(outDir, name), Buffer.from(r.data, 'base64'));
  console.log('shot', name);
}
await cdp('Page.enable');
const READY = `!!(window.ptqJumpToTick && document.querySelector('#feed .feed-item'))`;
await shot('desktop-1440x900-tick0.png', { width: 1440, height: 900, ready: READY, act: 'window.ptqJumpToTick(0)' });
await shot('desktop-1440x900-tick120.png', { width: 1440, height: 900, ready: READY, act: 'window.ptqJumpToTick(120)' });
await shot('mobile-390x844-tick0.png', { width: 390, height: 844, mobile: true, ready: READY, act: 'window.ptqJumpToTick(0)' });
await shot('mobile-390x844-tick120.png', { width: 390, height: 844, mobile: true, ready: READY, act: 'window.ptqJumpToTick(120)' });
await shot('desktop-1440x900-compare.png', {
  width: 1440, height: 900, url: `${baseUrl}?compare=fixtures/nascimento`,
  ready: `!!document.querySelector('#compare .mrow')`,
  act: `(() => { window.ptqJumpToTick(0); const a = document.querySelector('aside'); a.scrollTop = a.scrollHeight; })()`,
});
await shot('desktop-1440x900-forge.png', {
  width: 1440, height: 900, url: `${baseUrl}?forge=fixtures/forge-v1`,
  ready: `!!document.querySelector('#forge .mrow')`,
  act: `(() => { window.ptqJumpToTick(0); document.querySelector('#forgetitle').scrollIntoView(); })()`,
});
ws.close(); chrome.kill();
console.log('screenshots em', outDir);
