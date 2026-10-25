"""Génère l'icône (fennec dans un diamant) en PNG 512 + ICO multi-tailles.

C'est un dessin PROCÉDURAL de remplacement : si vous avez votre propre icône, déposez simplement assets/fennec_diamond.ico (et .png) : build_windows.bat la préfère.
Usage : python tools/make_icon.py [--force]
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"


def draw(size: int = 512) -> Image.Image:
    S = size * 4                                              # sur-échantillonnage pour des bords nets
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    c = S // 2
    def poly(pts, fill, outline=None, w=0):
        d.polygon(pts, fill=fill, outline=outline, width=w)
    r = int(S * 0.47)
    diamond = [(c, c - r), (c + r, c), (c, c + r), (c - r, c)]
    # fond du diamant : dégradé vertical bleu nuit -> cyan
    grad = Image.new("RGBA", (S, S)); gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S; gd.line([(0, y), (S, y)], fill=(int(10 + 20 * t), int(24 + 70 * t), int(52 + 110 * t), 255))
    mask = Image.new("L", (S, S), 0); ImageDraw.Draw(mask).polygon(diamond, fill=255)
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    d.line(diamond + [diamond[0]], fill=(120, 190, 255, 255), width=int(S * 0.012), joint="curve")
    # fennec : grandes oreilles + museau (silhouette stylisée)
    sand = (232, 190, 130, 255); dark = (150, 100, 55, 255); ink = (12, 18, 30, 255)
    ear_l = [(c - int(r * .50), c - int(r * .62)), (c - int(r * .13), c - int(r * .02)), (c - int(r * .52), c + int(r * .08))]
    ear_r = [(c + int(r * .50), c - int(r * .62)), (c + int(r * .13), c - int(r * .02)), (c + int(r * .52), c + int(r * .08))]
    poly(ear_l, sand); poly(ear_r, sand)
    poly([(c - int(r * .40), c - int(r * .44)), (c - int(r * .19), c - int(r * .06)), (c - int(r * .42), c)], (214, 120, 110, 255))
    poly([(c + int(r * .40), c - int(r * .44)), (c + int(r * .19), c - int(r * .06)), (c + int(r * .42), c)], (214, 120, 110, 255))
    head = [(c - int(r * .36), c - int(r * .08)), (c + int(r * .36), c - int(r * .08)), (c + int(r * .22), c + int(r * .30)), (c, c + int(r * .50)), (c - int(r * .22), c + int(r * .30))]
    poly(head, sand)
    poly([(c - int(r * .36), c - int(r * .08)), (c - int(r * .12), c - int(r * .08)), (c - int(r * .22), c + int(r * .30))], dark)
    poly([(c + int(r * .36), c - int(r * .08)), (c + int(r * .12), c - int(r * .08)), (c + int(r * .22), c + int(r * .30))], dark)
    for sx in (-1, 1):                                       # yeux
        ex = c + sx * int(r * .16); ey = c + int(r * .06); d.ellipse([ex - int(r * .045), ey - int(r * .03), ex + int(r * .045), ey + int(r * .03)], fill=ink)
    d.polygon([(c - int(r * .05), c + int(r * .40)), (c + int(r * .05), c + int(r * .40)), (c, c + int(r * .47))], fill=ink)   # truffe
    glow = im.filter(ImageFilter.GaussianBlur(S // 90)); out = Image.alpha_composite(glow, im)
    return out.resize((size, size), Image.LANCZOS)


def main(force: bool = False) -> int:
    OUT.mkdir(exist_ok=True)
    png, ico = OUT / "fennec_diamond.png", OUT / "fennec_diamond.ico"
    if not force and png.exists() and ico.exists():
        print("icône existante conservée (utilisez --force pour la régénérer) :", png); return 0
    img = draw(512); img.save(png)
    img.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icône générée :", png, ico); return 0


if __name__ == "__main__":
    sys.exit(main("--force" in sys.argv))
