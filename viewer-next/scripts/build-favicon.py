#!/usr/bin/env python3
"""Deriva o favicon e a marca do lockup de `assets/cover.webp` (F5 — VIS-09).

Derivação mecânica e reproduzível (a spec permite derivados mecânicos da capa;
arte nova, não): recorte quadrado de lado = largura da capa, centrado no
reator "quantum core" — o centro visual da arte (~47% × 47% da imagem) — e
redimensionamento com Lanczos. Nenhum desenho novo entra: é a capa, recortada.

Saídas em `public/` (versionadas, < 50 KB cada — teto VIS-09):
  favicon.ico          16/32/48 px embutidos
  favicon-16.png       16×16
  favicon-32.png       32×32
  ptq-mark-64.png      64×64 — marca do lockup no header do viewer
  apple-touch-icon.png 180×180

Uso: python3 scripts/build-favicon.py   (requer Pillow; roda offline)
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
COVER = ROOT.parent / "assets" / "cover.webp"
PUBLIC = ROOT / "public"

# Centro visual da capa (o reator), como fração da imagem — conferido na arte.
CORE_CENTER = (0.47, 0.47)


def core_crop(im: Image.Image) -> Image.Image:
    w, h = im.size
    side = min(w, h)  # quadrado inscrito: seguro para capa retrato ou paisagem
    assert side > 0
    cx, cy = int(CORE_CENTER[0] * w), int(CORE_CENTER[1] * h)
    x0 = max(0, min(w - side, cx - side // 2))
    y0 = max(0, min(h - side, cy - side // 2))
    return im.crop((x0, y0, x0 + side, y0 + side))


def main() -> None:
    im = Image.open(COVER).convert("RGB")
    crop = core_crop(im)
    PUBLIC.mkdir(exist_ok=True)
    outputs = {
        "favicon-16.png": 16,
        "favicon-32.png": 32,
        "ptq-mark-64.png": 64,
        "apple-touch-icon.png": 180,
    }
    for name, size in outputs.items():
        out = PUBLIC / name
        img = crop.resize((size, size), Image.LANCZOS)
        # Teto da VIS-09: derivado < 50 KB. O 180×180 RGB da arte isométrica
        # detalhada passa disso (~78 KB); paleta adaptativa de 256 cores o traz
        # para baixo do teto sem desenho novo — só quantização do mesmo recorte.
        if img.size[0] > 64:
            img = img.quantize(colors=256, method=Image.MEDIANCUT)
        img.save(out, optimize=True)
        print(f"{name}: {size}x{size}, {out.stat().st_size} B")
    ico = PUBLIC / "favicon.ico"
    crop.save(ico, sizes=[(16, 16), (32, 32), (48, 48)])
    print(f"favicon.ico: 16/32/48, {ico.stat().st_size} B")


if __name__ == "__main__":
    main()
