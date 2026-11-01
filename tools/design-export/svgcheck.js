(() => {
  const svg = document.querySelector('svg.dg');
  const inv = svg.getScreenCTM().inverse();
  const box = el => {
    const b = el.getBBox(), M = inv.multiply(el.getScreenCTM());
    const pts = [[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(([x,y]) => { const p = svg.createSVGPoint(); p.x=x; p.y=y; const q = p.matrixTransform(M); return [q.x,q.y]; });
    const xs = pts.map(p=>p[0]), ys = pts.map(p=>p[1]);
    return { x1: Math.min(...xs), y1: Math.min(...ys), x2: Math.max(...xs), y2: Math.max(...ys) };
  };
  const name = el => { const g = el.closest('g[id]'); return (g ? '#' + g.id : '') + ' "' + (el.textContent || '').trim().slice(0, 34) + '"'; };
  const r = n => Math.round(n * 10) / 10;
  const inter = (a, b, pad = 0) => !(a.x2 <= b.x1 + pad || b.x2 <= a.x1 + pad || a.y2 <= b.y1 + pad || b.y2 <= a.y1 + pad);
  const inside = (a, b, m = 0) => a.x1 >= b.x1 + m && a.x2 <= b.x2 - m && a.y1 >= b.y1 + m && a.y2 <= b.y2 - m;
  const texts = [...svg.querySelectorAll('text')].filter(t => !t.closest('defs')).map(t => ({ el: t, b: box(t) }));
  // ink box of a text line: tighten vertically to roughly cap-height..baseline so stacked lines don't false-positive
  texts.forEach(t => { const fs = parseFloat(getComputedStyle(t.el).fontSize); const base = t.el.getScreenCTM ? null : null; const h = t.b.y2 - t.b.y1; t.ink = { x1: t.b.x1, x2: t.b.x2, y1: t.b.y1 + h * 0.22, y2: t.b.y2 - h * 0.22 }; t.fs = fs; });
  const rects = [...svg.querySelectorAll('rect')].filter(x => x.id !== 'fondo' && !x.closest('defs')).map(x => ({ el: x, b: box(x) }));
  const out = { overflow: [], cross: [], textText: [], textPath: [], boxBox: [] };
  // 1) containment: smallest rect containing the text's center must contain the whole text with >= 5px side padding
  for (const t of texts) {
    const cx = (t.b.x1 + t.b.x2) / 2, cy = (t.b.y1 + t.b.y2) / 2;
    const hosts = rects.filter(R => cx > R.b.x1 && cx < R.b.x2 && cy > R.b.y1 && cy < R.b.y2).sort((a, b) => (a.b.x2 - a.b.x1) * (a.b.y2 - a.b.y1) - (b.b.x2 - b.b.x1) * (b.b.y2 - b.b.y1));
    if (!hosts.length) continue;
    const H = hosts[0].b;
    const padL = t.ink.x1 - H.x1, padR = H.x2 - t.ink.x2;
    if (padL < 5 || padR < 5 || t.ink.y1 < H.y1 || t.ink.y2 > H.y2) out.overflow.push(name(t.el) + ' padL=' + r(padL) + ' padR=' + r(padR) + ' in ' + (hosts[0].el.getAttribute('class') || hosts[0].el.closest('g[id]')?.id || 'rect'));
  }
  // 2) text crossing any rect border (partially inside)
  for (const t of texts) for (const R of rects) {
    if (inter(t.ink, R.b) && !inside(t.ink, R.b)) { const area = (R.b.x2 - R.b.x1) * (R.b.y2 - R.b.y1); out.cross.push(name(t.el) + ' × rect ' + (R.el.getAttribute('class') || R.el.closest('g[id]')?.id || '') + ' [' + r(R.b.x1) + ',' + r(R.b.y1) + ' ' + r(R.b.x2 - R.b.x1) + 'x' + r(R.b.y2 - R.b.y1) + ']'); }
  }
  // 3) text vs text
  for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) if (inter(texts[i].ink, texts[j].ink, .5)) out.textText.push(name(texts[i].el) + ' ↔ ' + name(texts[j].el));
  // 4) arrows / connectors through text (sample along every stroked path outside <defs>)
  const paths = [...svg.querySelectorAll('path')].filter(p => !p.closest('defs') && getComputedStyle(p).stroke !== 'none');
  for (const p of paths) {
    const L = p.getTotalLength(), M = inv.multiply(p.getScreenCTM());
    const hits = new Set();
    for (let s = 0; s <= L; s += 2) { const q = p.getPointAtLength(s).matrixTransform(M); for (const t of texts) if (q.x > t.ink.x1 + 1 && q.x < t.ink.x2 - 1 && q.y > t.ink.y1 && q.y < t.ink.y2) hits.add(name(t.el)); }
    hits.forEach(hn => out.textPath.push((p.id || p.parentElement.id || p.getAttribute('d').slice(0, 24)) + ' → ' + hn));
  }
  // 5) box vs box (role boxes and notes only): partial overlaps
  const roleBoxes = rects.filter(R => /caja-|nota/.test((R.el.getAttribute('class') || '') + ' ' + (R.el.closest('.nota-decision') ? 'nota' : '')));
  for (let i = 0; i < roleBoxes.length; i++) for (let j = i + 1; j < roleBoxes.length; j++) { const A = roleBoxes[i].b, B = roleBoxes[j].b; if (inter(A, B) && !inside(A, B) && !inside(B, A)) out.boxBox.push((roleBoxes[i].el.closest('g[id]')?.id) + ' ∩ ' + (roleBoxes[j].el.closest('g[id]')?.id)); }
  out.counts = Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v.length]));
  out.fonts = { t: getComputedStyle(svg.querySelector('.t')).fontFamily.split(',')[0] + ' ' + getComputedStyle(svg.querySelector('.t')).fontStretch, d: getComputedStyle(svg.querySelector('.d')).fontFamily.split(',')[0] };
  return out;
})()
