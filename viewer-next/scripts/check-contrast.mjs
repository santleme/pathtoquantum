// Contraste WCAG da paleta do viewer (F6 — VIS-10): pares medidos, não estimados.
// Texto principal ≥ 4,5:1; texto secundário/destaques ≥ 3:1 (aceitação da spec).
// Uso: node scripts/check-contrast.mjs (sai != 0 se algum par reprovar).
function lum(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (fg, bg) => {
  const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
};
const PAIRS = [
  // [nome, fg, bg, mínimo]
  ['texto principal / fundo', '#e8ecf6', '#0b1020', 4.5],
  ['texto principal / painel', '#e8ecf6', '#131a2e', 4.5],
  ['texto principal / mapa', '#e8ecf6', '#0d1526', 4.5],
  ['secundário (dim) / fundo', '#8b96b8', '#0b1020', 3],
  ['secundário (dim) / painel', '#8b96b8', '#131a2e', 3],
  ['ouro (data/marcos) / fundo', '#ffd166', '#0b1020', 3],
  ['ouro / painel', '#ffd166', '#131a2e', 3],
  ['verde (caixa) / painel', '#9ae6b4', '#131a2e', 3],
  ['rosa (falida/erro) / painel', '#ff8fa3', '#131a2e', 3],
  ['azul (tier estrutural) / painel', '#7ea8d8', '#131a2e', 3],
  ['texto da rotina (feed) / painel', '#c3cbdf', '#131a2e', 3],
  ['ink sobre ouro (selo "novo")', '#0b1020', '#ffd166', 4.5],
];
let fail = 0;
for (const [name, fg, bg, min] of PAIRS) {
  const r = ratio(fg, bg);
  const ok = r >= min;
  if (!ok) fail++;
  console.log(`${ok ? 'OK  ' : 'FALHA'} ${name}: ${r.toFixed(2)}:1 (mín ${min}:1)`);
}
console.log(fail ? `\n${fail} par(es) abaixo do piso VIS-10` : '\nTodos os pares acima do piso VIS-10');
process.exit(fail ? 1 : 0);
