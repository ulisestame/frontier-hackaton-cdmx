# Builds the PNG export page from the live architecture page (SVG + caption), so the PNG never drifts from the site.
import re, sys, html
from pathlib import Path
src = Path(__file__).resolve().parents[2] / "design-site" / "arquitectura" / "index.html"
out = sys.argv[1]
h = open(src, encoding="utf-8").read()
svg = h[h.index("<svg id=\"diagrama\""):h.index("</svg>") + len("</svg>")]
cap = re.search(r'<figcaption class="note">(.*?)</figcaption>', h, re.S).group(1)
page = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400..700&family=Martian+Mono:wdth,wght@75..100,400..800&display=swap">
<link rel="stylesheet" href="http://127.0.0.1:8080/assets/tema.css">
<style>
  body{{min-height:0}}
  .export{{width:1600px;padding:44px 49px 40px}}
  .export .eyebrow{{font-size:14px;margin:0 0 16px}}
  .export .ttl{{display:flex;align-items:flex-end;justify-content:space-between;gap:32px;margin:0 0 24px}}
  .export h1{{font-size:42px;margin:0}}
  .export .sub{{margin:10px 0 0;font-size:19px}}
  .export .byline{{margin:0;text-align:right}}
  .export .frame{{border:1px solid var(--rule)}}
  .export svg{{display:block;width:1500px;height:auto}}
  .export .note{{max-width:none;margin:16px 0 0}}
  .redact::after{{animation:none}}
</style>
</head>
<body>
<div class="export">
  <p class="eyebrow">Reto 1 · Vende los datos sin vender a <span class="redact">la gente</span></p>
  <div class="ttl">
    <div><h1>Kipu Pay <span class="dot">·</span> Corpus anonimizado</h1><p class="sub">Diagrama de arquitectura</p></div>
    <p class="byline">Ulises Fabian Gutierrez Tame · Reto 1 · Frontier Hackathon CDMX · 31 oct 2026</p>
  </div>
  <div class="frame">{svg}</div>
  <p class="note">{cap}</p>
</div>
</body>
</html>
"""
open(out, "w", encoding="utf-8").write(page)
print("export page:", out, len(page), "bytes")
