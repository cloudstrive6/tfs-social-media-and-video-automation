/* TFS atlas blocks v3 (2026-11-25): globe, stamp, checklist, line chart, bar chart, waffle, balance bar, date cards,
 * media card with side list and honesty chips. Borrowed from the Worldwire "briefing" grammar (see the Bryce-Brain
 * page answers/tfs-worldwire-briefing-style-2026-11.md), drawn in the TFS paper palette.
 *
 * Loaded by atlas.js through window.TFS_BLOCKS(ctx): it adds builders to ctx.build and returns
 * {stamp(s), tick(t)}. Every motion is on the paused GSAP timeline; anything that must be recomputed per frame
 * (the globe, count-ups, pulses) is a pure function of time called from tick(t), which atlas.js drives with a
 * getter/setter tween, so HyperFrames can seek any frame in any order.
 * Each infographic builds frame, then data, then label, then one annotation; build steps use the item `at` times
 * the planner resolved from spoken words, else an even spread.
 */
window.TFS_BLOCKS = function (ctx) {
  const { W, H, V, U, C, tl, el, esc, px, layer, inOut, badge, build } = ctx;
  const SAFE = !!ctx.SAFE;                                  // vertical safe area: content between 6% and 86% of the width
  // a long label must wrap, never stretch the panel past 86% of the width (OFW dry run: a waffle panel ran to 96%)
  const PANEL_X = (top) => (SAFE ? SAFE_POS : `left:50%;top:${top}%;transform:translateX(-50%)`);
  const L = window.TFSLIB;
  const MONO = `'DejaVu Sans Mono',Consolas,'Courier New',monospace`;
  const GOLD = "#B98100";                                   // gold that reads on paper; C.yel stays the fill
  const col = (c, dflt) => ({ red: C.red, teal: C.teal, ink: C.ink, gold: GOLD }[c] || dflt || C.red);
  const TICK = [];
  const ease = (name) => gsap.parseEase(name);
  const io2 = ease("power2.inOut"), o2 = ease("power2.out"), back = ease("back.out(2)");
  let uid = 0;
  const SAFE_POS = "@safe";
  // on a safe vertical the panel is centred in the band between the handle (17%) and the captions (69%) and spans
  // the safe width, so the phone screen is filled and nothing crowds the handle (round 2 reviews: bottom 45% empty)
  const panel = (inner, style) => style === SAFE_POS
    ? `<div style="position:absolute;left:6%;right:14%;top:17%;bottom:31%;display:flex;flex-direction:column;justify-content:safe center">` +
      `<div class="pnl" style="position:relative;background:${C.sheet};border:${px(4)} solid ${C.ink};border-radius:${px(18)};` +
      `box-shadow:${px(8)} ${px(8)} 0 ${C.ink};padding:${px(24)} ${px(28)}">${inner}</div></div>`
    : `<div class="pnl" style="position:absolute;background:${C.sheet};border:${px(4)} solid ${C.ink};` +
    `border-radius:${px(18)};box-shadow:${px(8)} ${px(8)} 0 ${C.ink};padding:${px(24)} ${px(28)};${style}">${inner}</div>`;
  const kicker = (t) => t ? `<div style="font:700 ${px(V ? 22 : 20)} ${MONO};letter-spacing:3px;color:${C.muted};margin-bottom:${px(12)}">${esc(t)}</div>` : "";
  const times = (items, s, lead, gap) => L.stepTimes(items, s.t0, s.t1, lead, gap);

  // ------------------------------------------------------------------ stamp (any shot)
  function stamp(s) {
    const st = s.stamp;
    if (!st || !st.text) return;
    const at = typeof st.at === "number" ? st.at : s.t0 + 0.5;
    const c = col(st.color, C.red);
    // long stamps shrink to fit about 82% of the width (Anton caps advance about 0.5 em; dry run 3 ran edge to edge)
    const fs = Math.min((V ? 66 : 70) * U, ((SAFE ? 0.72 : 0.82) * W - 80 * U) / (Math.max(1, String(st.text).length) * 0.5));
    const n = el("div", "position:absolute;inset:0;pointer-events:none;opacity:0");
    // verticals: in the band between the panels (top 20 to 55%) and the captions (72%), so it never hides the number
    const top = st.pos === "top" ? (V ? 23 : 15) : st.pos === "mid" ? (V ? 40 : 48) : (V ? 67 : 15);   // verticals: below source boxes (about 60%), above the captions (72%)
    n.innerHTML = `<div style="position:absolute;left:${SAFE ? 46 : 50}%;top:${top}%;transform:translate(-50%,-50%) rotate(-6deg)">` +
      `<div class="stp" style="font:400 ${fs.toFixed(0)}px/1 Anton;letter-spacing:3px;color:${c};white-space:nowrap;` +
      `border:${px(7)} solid ${c};border-radius:${px(10)};padding:${px(8)} ${px(26)};background:rgba(248,242,228,.94);` +
      `box-shadow:0 0 ${px(26)} ${c}88, inset 0 0 0 ${px(3)} rgba(248,242,228,.94), inset 0 0 0 ${px(6)} ${c}55;` +
      `text-shadow:0 0 ${px(12)} ${c}66">${esc(st.text)}</div></div>`;
    const b = n.querySelector(".stp");
    tl.set(n, { opacity: 1 }, at);
    tl.fromTo(b, { scale: 1.3, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.3, ease: "back.out(2.4)" }, at);
    tl.fromTo(b, { filter: "brightness(1.25)" }, { filter: "brightness(1)", duration: 0.5, ease: "power1.out" }, at + 0.12);
    tl.to(n, { opacity: 0, duration: 0.2 }, Math.max(at + 0.4, s.t1 - 0.2));
  }

  // ------------------------------------------------------------------ number tags (a spoken number the plan missed)
  function tags(s) {
    (s.tags || []).forEach((tg, i) => {
      const at = typeof tg.at === "number" ? tg.at : s.t0 + 0.3;
      const n = el("div", "position:absolute;inset:0;pointer-events:none;opacity:0");
      n.innerHTML = `<div style="position:absolute;left:6%;top:${V ? 60 - i * 5 : 70 - i * 7}%;font:400 ${px(V ? 54 : 50)}/1 Anton;` +
        `color:${C.ink};background:${C.yel};border:${px(4)} solid ${C.ink};border-radius:${px(10)};padding:${px(8)} ${px(18)};` +
        `box-shadow:${px(6)} ${px(6)} 0 ${C.ink};white-space:nowrap">${esc(tg.text)}</div>`;
      tl.fromTo(n, { opacity: 0, x: -30 * U }, { opacity: 1, x: 0, duration: 0.25, ease: "power2.out" }, at);
      tl.to(n, { opacity: 0, duration: 0.2 }, Math.max(at + 1.6, s.t1 - 0.2));
    });
  }

  // ------------------------------------------------------------------ globe
  build.globe = function (s) {
    const G = ctx.globe;
    if (!G) throw new Error("globe shot without SPEC.geo.globe");
    const id = `g${uid++}`;
    const n = layer(true);
    const cx = W / 2, cy = H * (V ? (SAFE ? 0.44 : 0.40) : 0.5), R0 = V ? W * 0.40 : H * 0.36;
    const f = s.focus || { lon: 121.8, lat: 12.5 };
    const zoomTo = s.zoom || 2.6;
    const lam0 = f.lon - 75, phi0 = Math.max(-25, Math.min(25, f.lat * 0.4));
    const lam1 = f.lon, phi1 = Math.max(-60, Math.min(60, f.lat));
    const rotAt = s.t0 + 0.15, rotDur = Math.min(2.4, Math.max(1.2, (s.t1 - s.t0) * 0.35));
    const zoomAt = typeof s.zoomAt === "number" ? s.zoomAt : rotAt + rotDur * 0.55, zoomDur = 1.6;
    const hl = (s.highlight || []).map((h) => ({ ...h, rings: (G.find((c) => c.iso === h.iso) || { rings: [] }).rings }));
    const places = s.places || [], arcs = s.arcs || [];
    const land = G.map((c) => c.rings).flat();
    const grat = L.graticule(20);
    n.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="position:absolute;inset:0;overflow:visible">` +
      `<defs><filter id="${id}gl" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="${(7 * U).toFixed(1)}" result="b"/>` +
      `<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>` +
      `<radialGradient id="${id}sea" cx="42%" cy="38%" r="70%"><stop offset="0" stop-color="#F6EFDF"/><stop offset="1" stop-color="#DCCCAA"/></radialGradient></defs>` +
      `<circle class="sea" fill="url(#${id}sea)" stroke="none"/>` +
      `<path class="grat" fill="none" stroke="#B9A47C" stroke-width="${(1.1 * U).toFixed(1)}" stroke-dasharray="${(3 * U).toFixed(1)} ${(5 * U).toFixed(1)}"/>` +
      `<path class="land" fill="#E2D3B3" stroke="#9C8763" stroke-width="${(1.0 * U).toFixed(1)}" stroke-linejoin="round"/>` +
      hl.map((h, i) => `<path class="hl hl${i}" fill="${col(h.color)}" fill-opacity="0" stroke="${col(h.color)}" stroke-opacity="0" stroke-width="${(2 * U).toFixed(1)}" filter="url(#${id}gl)"/>`).join("") +
      `<circle class="rim" fill="none" stroke="${C.ink}" stroke-width="${(2.2 * U).toFixed(1)}"/>` +
      arcs.map((a, i) => `<path class="arc arc${i}" fill="none" stroke="${C.ink}" stroke-width="${(3 * U).toFixed(1)}" stroke-dasharray="${(9 * U).toFixed(1)} ${(7 * U).toFixed(1)}" stroke-linecap="round"/>` +
        `<circle class="mk mk${i}" r="${(9 * U).toFixed(1)}" fill="${C.red}" stroke="#fff" stroke-width="${(3 * U).toFixed(1)}" opacity="0"/>`).join("") +
      places.map((p, i) => `<g class="pl pl${i}" opacity="0"><circle class="pr" fill="none" stroke="${C.red}" stroke-width="${(2.5 * U).toFixed(1)}"/>` +
        `<circle class="pd" r="${(8 * U).toFixed(1)}" fill="${C.red}" stroke="#fff" stroke-width="${(2.5 * U).toFixed(1)}"/>` +
        `<text class="pt" font-family="${MONO}" font-weight="700" font-size="${(V ? 26 : 24) * U}" letter-spacing="2" fill="${C.ink}" stroke="${C.sheet}" stroke-width="${(6 * U).toFixed(1)}" paint-order="stroke">${esc(String(p.name).toUpperCase().replace(/\s+/g, " "))}</text></g>`).join("") +
      `</svg>` +
      (s.label ? `<div class="glab" style="position:absolute;left:6%;top:${V ? 17 : 72}%;${SAFE ? "max-width:74%;" : ""}font:800 ${px(V ? 40 : 34)} Montserrat;color:${C.ink};background:${C.yel};` +
        `padding:${px(10)} ${px(18)};border-radius:${px(8)};box-shadow:${px(5)} ${px(5)} 0 ${C.ink}">${esc(s.label)}</div>` : "") +
      (s.src ? `<div style="position:absolute;left:6%;top:${V ? 60 : 88}%">${badge(s.src)}</div>` : "");
    inOut(n, s, { scale: 0.96 });
    const q = (c) => n.querySelector(c);
    const sea = q(".sea"), rim = q(".rim"), gp = q(".grat"), lp = q(".land");
    const hlEls = hl.map((_, i) => q(`.hl${i}`));
    const hlAt = hl.map((h, i) => typeof h.at === "number" ? h.at : rotAt + rotDur + 0.2 + i * 0.8);
    hlEls.forEach((e, i) => tl.to(e, { attr: { "fill-opacity": 0.85, "stroke-opacity": 1 }, duration: 0.6, ease: "power1.out" }, hlAt[i]));
    const plAt = times(places, s, rotDur + 0.6, 0.6);
    const arcAt = arcs.map((a, i) => typeof a.at === "number" ? a.at : rotAt + rotDur + 0.6 + i * 1.4);
    const plEls = places.map((_, i) => q(`.pl${i}`));
    plEls.forEach((e, i) => tl.to(e, { opacity: 1, duration: 0.2 }, plAt[i]));
    if (s.label) tl.fromTo(q(".glab"), { opacity: 0, x: -40 * U }, { opacity: 1, x: 0, duration: 0.35, ease: "power2.out" }, rotAt + rotDur);
    TICK.push((t) => {
      if (t < s.t0 - 0.05 || t > s.t1 + 0.05) return;
      const pr = io2(L.prog(t, rotAt, rotDur));
      const settle = L.prog(t, rotAt + rotDur, s.t1 - rotAt - rotDur);
      const drift = 10 * settle;                       // keeps turning and creeping in after it lands: never static
      const lam = lam0 + (lam1 - lam0) * pr + drift, phi = phi0 + (phi1 - phi0) * pr;
      const R = R0 * (1 + (zoomTo - 1) * io2(L.prog(t, zoomAt, zoomDur))) * (1 + 0.08 * settle);
      // keep the focus point on screen centre while zooming: the view is centred on (lam, phi) already
      sea.setAttribute("cx", cx); sea.setAttribute("cy", cy); sea.setAttribute("r", R);
      rim.setAttribute("cx", cx); rim.setAttribute("cy", cy); rim.setAttribute("r", R);
      gp.setAttribute("d", L.pathRings(grat, lam, phi, R, cx, cy, false));
      lp.setAttribute("d", L.pathRings(land, lam, phi, R, cx, cy));
      hlEls.forEach((e, i) => { if (t >= hlAt[i] - 0.05) e.setAttribute("d", L.pathRings(hl[i].rings, lam, phi, R, cx, cy)); });
      plEls.forEach((e, i) => {
        if (t < plAt[i]) return;
        const p = places[i], pt = L.point(p.lon, p.lat, lam, phi, R, cx, cy);
        e.setAttribute("visibility", pt.vis ? "visible" : "hidden");
        const k = back(L.prog(t, plAt[i], 0.3));
        const d = e.querySelector(".pd"), ring = e.querySelector(".pr"), tx = e.querySelector(".pt");
        d.setAttribute("cx", pt.x); d.setAttribute("cy", pt.y); d.setAttribute("r", (8 * U * k).toFixed(1));
        const ph = ((t - plAt[i]) % 1.6) / 1.6;                                      // pulse every 1.6 s
        ring.setAttribute("cx", pt.x); ring.setAttribute("cy", pt.y); ring.setAttribute("r", (U * (10 + 26 * ph)).toFixed(1));
        ring.setAttribute("opacity", (1 - ph).toFixed(2));
        const right = pt.x < W * 0.72;
        tx.setAttribute("x", pt.x + (right ? 18 : -18) * U); tx.setAttribute("y", pt.y + 9 * U);
        tx.setAttribute("text-anchor", right ? "start" : "end");
      });
      arcs.forEach((a, i) => {
        const pa = L.prog(t, arcAt[i], 1.3);
        const path = q(`.arc${i}`), mk = q(`.mk${i}`);
        if (pa <= 0) { path.setAttribute("d", ""); mk.setAttribute("opacity", 0); return; }
        const u = io2(pa);
        path.setAttribute("d", L.arcPath(a.from, a.to, u, lam, phi, R, cx, cy));
        if (a.marker !== false) {
          const span = L.angle(a.from, a.to), lift = Math.min(0.22, 0.04 + span / 400);
          const ll = L.slerp(a.from, a.to, u), pt = L.point(ll[0], ll[1], lam, phi, R, cx, cy, lift * Math.sin(Math.PI * u));
          mk.setAttribute("cx", pt.x); mk.setAttribute("cy", pt.y); mk.setAttribute("opacity", pt.vis ? 1 : 0);
        }
      });
    });
  };

  // ------------------------------------------------------------------ checklist (what the law covers, fact-check verdicts)
  const MARK = { tick: "M 12 28 L 23 39 L 43 15", x: "M 15 15 L 39 39 M 39 15 L 15 39", warn: "M 27 11 L 27 31 M 27 40 L 27 42" };
  build.checklist = function (s) {
    const n = layer(true);
    const items = (s.items || []).slice(0, 5);
    const rows = items.map((it) => {
      const mk = it.mark || "tick", c = mk === "tick" ? C.teal : mk === "x" ? C.red : GOLD;
      return `<div class="cr" style="display:flex;align-items:center;gap:${px(20)};padding:${px(12)} ${px(16)};margin-top:${px(14)};` +
        `border:${px(3)} solid ${C.ink};border-radius:${px(12)};background:#fff">` +
        `<div style="flex:none;width:${px(56)};height:${px(56)};border:${px(3)} solid ${C.ink};border-radius:${px(10)};background:#fff">` +
        `<svg viewBox="0 0 54 54" width="100%" height="100%"><path class="mk" d="${MARK[mk]}" fill="none" stroke="${c}" stroke-width="7" ` +
        `stroke-linecap="round" stroke-linejoin="round" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100"/></svg></div>` +
        `<div class="ct" style="flex:1;min-width:0;font:800 ${px(V ? 31 : 29)}/1.22 Montserrat;color:${C.ink}">${esc(it.text)}</div>` +
        (it.label ? `<div class="cn" style="flex:none;font:700 ${px(18)} ${MONO};letter-spacing:2px;color:${c};border:${px(2)} solid ${c};` +
          `border-radius:${px(6)};padding:${px(4)} ${px(8)};opacity:0">${esc(it.label)}</div>` : "") + `</div>`;
    }).join("");
    n.innerHTML = panel(kicker(s.head) + rows + (s.src ? `<div>${badge(s.src)}</div>` : ""),
      SAFE ? SAFE_POS : `left:${V ? 6 : 22}%;right:${V ? 6 : 22}%;top:${V ? 24 : 20}%`);
    inOut(n, s, { scale: 0.97, y: 20 * U });
    const at = times(items, s, 0.45, 0.8);
    n.querySelectorAll(".cr").forEach((row, i) => {
      const mk = items[i].mark || "tick";
      tl.fromTo(row, { opacity: 0, x: -40 * U }, { opacity: 1, x: 0, duration: 0.25, ease: "power2.out" }, at[i]);
      tl.to(row.querySelector(".mk"), { attr: { "stroke-dashoffset": 0 }, duration: 0.15, ease: "none" }, at[i] + 0.25);
      if (mk !== "tick") {
        const c = mk === "x" ? C.red : GOLD;
        tl.to(row, { backgroundColor: mk === "x" ? "#F7D9DD" : "#FBEFC8", borderColor: c, duration: 0.2 }, at[i] + 0.3);
        tl.to(row.querySelector(".ct"), { color: c, duration: 0.2 }, at[i] + 0.3);
      }
      const note = row.querySelector(".cn");
      if (note) tl.to(note, { opacity: 1, duration: 0.2 }, at[i] + 0.35);
    });
  };

  // ------------------------------------------------------------------ line chart: headline counts up with the draw
  build.linechart = function (s) {
    const n = layer(true);
    const pts = (s.items || []).filter((it) => typeof it.num === "number").slice(0, 12);
    if (pts.length < 2) throw new Error("linechart needs 2 or more numeric points");
    const cw = Math.round(W * (V ? 0.7 : 0.66)), ch = Math.round(H * (V ? 0.2 : 0.34)), pad = 18 * U;   // panel within 88% of a vertical
    const nums = pts.map((p) => p.num), lo0 = Math.min(...nums), hi0 = Math.max(...nums), sp = (hi0 - lo0) || Math.abs(hi0) || 1;
    const lo = lo0 - sp * 0.15, hi = hi0 + sp * 0.12;
    const X = (i) => pad + i * (cw - 2 * pad) / Math.max(1, pts.length - 1), Y = (v) => ch - pad - (v - lo) / (hi - lo) * (ch - 2 * pad);
    const d = pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(p.num).toFixed(1)}`).join("");
    const area = d + `L${X(pts.length - 1).toFixed(1)} ${ch - pad}L${X(0).toFixed(1)} ${ch - pad}Z`;
    const last = pts.length - 1;
    const grid = [0, 1, 2, 3].map((k) => `<line x1="${pad}" x2="${cw - pad}" y1="${(pad + k * (ch - 2 * pad) / 3).toFixed(1)}" y2="${(pad + k * (ch - 2 * pad) / 3).toFixed(1)}" stroke="#C9B691" stroke-width="${(1.5 * U).toFixed(1)}" stroke-dasharray="${(4 * U).toFixed(1)} ${(6 * U).toFixed(1)}"/>`).join("");
    const lab = (i, anchor) => pts[i] && pts[i].label ? `<text x="${X(i).toFixed(1)}" y="${(ch + 26 * U).toFixed(1)}" text-anchor="${anchor}" font-family="${MONO}" font-weight="700" font-size="${(19 * U).toFixed(1)}" letter-spacing="1" fill="${C.muted}">${esc(pts[i].label)}</text>` : "";
    const svg = `<svg class="lc" width="${cw}" height="${ch + 36 * U}" style="display:block;overflow:visible">${grid}` +
      `<path class="ar" d="${area}" fill="${C.red}" fill-opacity="0"/>` +
      `<path class="ln" d="${d}" fill="none" stroke="${C.red}" stroke-width="${(6 * U).toFixed(1)}" stroke-linejoin="round" stroke-linecap="round" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100"/>` +
      `<circle class="d0" cx="${X(0).toFixed(1)}" cy="${Y(pts[0].num).toFixed(1)}" r="${(9 * U).toFixed(1)}" fill="${C.ink}" opacity="0"/>` +
      `<circle class="hd" r="${(8 * U).toFixed(1)}" fill="${C.red}" opacity="0"/>` +
      `<circle class="pr" cx="${X(last).toFixed(1)}" cy="${Y(pts[last].num).toFixed(1)}" fill="none" stroke="${C.red}" stroke-width="${(3 * U).toFixed(1)}" opacity="0"/>` +
      `<circle class="d1" cx="${X(last).toFixed(1)}" cy="${Y(pts[last].num).toFixed(1)}" r="${(12 * U).toFixed(1)}" fill="${C.red}" stroke="#fff" stroke-width="${(3 * U).toFixed(1)}" opacity="0" style="filter:drop-shadow(0 0 ${px(8)} ${C.red})"/>` +
      lab(0, "start") + lab(last, "end") + `</svg>`;
    const callout = s.callout ? `<div class="co" style="position:absolute;left:${(X(last) + 28 * U - cw * 0.0).toFixed(0)}px;top:${(Y(pts[last].num) < ch * 0.45 ? Y(pts[last].num) + 34 * U : Y(pts[last].num) - 70 * U).toFixed(0)}px;` +
      `transform:translateX(-100%);font:400 ${px(V ? 46 : 42)}/1 Anton;color:#fff;background:${C.red};padding:${px(6)} ${px(14)};border-radius:${px(8)};white-space:nowrap;opacity:0">${esc(s.callout)}</div>` : "";
    n.innerHTML = panel(kicker(s.head) +
      `<div class="big" style="font:400 ${px(V ? 92 : 84)}/1 Anton;color:${C.red};margin-bottom:${px(16)};white-space:nowrap;opacity:0">${esc(L.figAt(s.big, 0))}</div>` +
      `<div style="position:relative">${svg}${callout}</div>` + (s.src ? `<div>${badge(s.src)}</div>` : ""),
      PANEL_X(V ? 19 : 14));
    inOut(n, s, { y: 30 * U });
    const drawAt = typeof s.bigAt === "number" && s.bigAt < s.t1 - 1 ? s.bigAt : s.t0 + 0.55, drawDur = 2.25;
    const coAt = typeof s.calloutAt === "number" && s.calloutAt >= drawAt ? s.calloutAt : drawAt + drawDur + 0.05;
    const q = (c) => n.querySelector(c);
    tl.to(q(".d0"), { opacity: 1, duration: 0.15 }, drawAt - 0.2);
    tl.to(q(".big"), { opacity: 1, duration: 0.15 }, drawAt - 0.2);   // the headline appears as it starts counting
    tl.to(q(".ln"), { attr: { "stroke-dashoffset": 0 }, duration: drawDur, ease: "none" }, drawAt);
    tl.to(q(".ar"), { attr: { "fill-opacity": 0.12 }, duration: 0.5 }, drawAt + drawDur);
    tl.fromTo(q(".d1"), { opacity: 0, scale: 0.3, transformOrigin: "50% 50%" }, { opacity: 1, scale: 1, duration: 0.25, ease: "back.out(2)" }, drawAt + drawDur);
    if (q(".co")) tl.fromTo(q(".co"), { opacity: 0, scale: 0.8 }, { opacity: 1, scale: 1, duration: 0.25, ease: "back.out(2)" }, coAt);
    const big = q(".big"), ln = q(".ln"), hd = q(".hd"), pr = q(".pr");
    TICK.push((t) => {
      if (t < s.t0 - 0.05 || t > s.t1 + 0.05) return;
      const u = L.prog(t, drawAt, drawDur);
      big.textContent = L.figAt(s.big, u);
      if (u > 0 && u < 1) {                                            // the head dot rides the tip of the line
        const p = ln.getPointAtLength(ln.getTotalLength() * u);
        hd.setAttribute("cx", p.x); hd.setAttribute("cy", p.y); hd.setAttribute("opacity", 1);
      } else hd.setAttribute("opacity", 0);
      if (u >= 1) {                                                    // the end dot keeps pulsing: never static
        const ph = ((t - drawAt - drawDur) % 1.4) / 1.4;
        pr.setAttribute("r", (U * (14 + 26 * ph)).toFixed(1)); pr.setAttribute("opacity", (1 - ph).toFixed(2));
      } else pr.setAttribute("opacity", 0);
    });
  };

  // ------------------------------------------------------------------ bar chart: bars grow with a count-up, then the arrow
  build.barchart = function (s) {
    const n = layer(true);
    const items = (s.items || []).slice(0, 4);
    if (!items.length) throw new Error("barchart needs items");
    const cw = Math.round(W * (V ? 0.7 : 0.6)), ch = Math.round(H * (V ? 0.26 : 0.4));
    const max = Math.max(...items.map((it) => Math.abs(it.num) || 0), 1e-9);
    const slot = cw / items.length, bw = Math.min(slot * 0.56, 190 * U), base = ch;
    const hgt = (it) => Math.max(6 * U, (Math.abs(it.num) || 0) / max * ch * 0.72);
    const bars = items.map((it, i) => {
      const x = slot * i + (slot - bw) / 2, c = col(it.color, i === items.length - 1 ? C.red : C.ink);
      return `<div class="bb" style="position:absolute;left:${x.toFixed(0)}px;top:${(base - hgt(it)).toFixed(0)}px;width:${bw.toFixed(0)}px;height:${hgt(it).toFixed(0)}px;` +
        `background:${c};border:${px(3)} solid ${C.ink};border-bottom:none;border-radius:${px(8)} ${px(8)} 0 0;transform-origin:50% 100%;transform:scaleY(0)"></div>` +
        `<div class="bv" style="position:absolute;left:${(x + bw / 2).toFixed(0)}px;top:${(base - 54 * U).toFixed(0)}px;transform:translateX(-50%);font:400 ${px(V ? 48 : 44)}/1 Anton;color:${c};white-space:nowrap;opacity:0">${esc(L.figAt(it.value, 0))}</div>` +
        `<div style="position:absolute;left:${(slot * i).toFixed(0)}px;width:${slot.toFixed(0)}px;top:${(base + 14 * U).toFixed(0)}px;text-align:center;font:700 ${px(V ? 21 : 19)}/1.25 ${MONO};letter-spacing:1px;color:${C.ink}">${esc(it.label)}</div>`;
    }).join("");
    // curved arrow from the first bar's top to the last bar's top, over the bars
    const a = items.length > 1 && s.callout;
    const x0 = slot * 0.5, x1 = slot * (items.length - 0.5);
    const y0 = base - hgt(items[0]) - 70 * U, y1 = base - hgt(items[items.length - 1]) - 70 * U;
    const top = Math.min(y0, y1) - 90 * U;
    const arrow = a ? `<svg style="position:absolute;left:0;top:0;overflow:visible" width="${cw}" height="${ch}">` +
      `<path class="aw" d="M${x0.toFixed(0)} ${y0.toFixed(0)} Q${((x0 + x1) / 2).toFixed(0)} ${top.toFixed(0)} ${(x1 - 10 * U).toFixed(0)} ${(y1 - 8 * U).toFixed(0)}" fill="none" stroke="${C.red}" stroke-width="${(5 * U).toFixed(1)}" stroke-linecap="round" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100"/>` +
      `<path class="ah" d="M${(x1 - 34 * U).toFixed(0)} ${(y1 - 24 * U).toFixed(0)} L${(x1 - 8 * U).toFixed(0)} ${(y1 - 6 * U).toFixed(0)} L${(x1 - 30 * U).toFixed(0)} ${(y1 + 12 * U).toFixed(0)}" fill="none" stroke="${C.red}" stroke-width="${(5 * U).toFixed(1)}" stroke-linecap="round" stroke-linejoin="round" opacity="0"/></svg>` +
      `<div class="at" style="position:absolute;left:${((x0 + x1) / 2).toFixed(0)}px;top:${(top + (Math.min(y0, y1) - top) * 0.5 - 40 * U).toFixed(0)}px;transform:translate(-50%,-50%) rotate(-3deg);` +
      `font:400 ${px(V ? 46 : 42)}/1 Anton;color:#fff;background:${C.red};padding:${px(6)} ${px(16)};border-radius:${px(8)};white-space:nowrap;opacity:0">${esc(s.callout)}</div>` : "";
    n.innerHTML = panel(kicker(s.head) + `<div style="position:relative;width:${cw}px;height:${(ch + 70 * U).toFixed(0)}px;margin-top:${px(a ? 120 : 30)}">` +
      `<div style="position:absolute;left:0;right:0;top:${base}px;border-top:${px(4)} solid ${C.ink}"></div>${bars}${arrow}</div>` +
      (s.src ? `<div>${badge(s.src)}</div>` : ""), PANEL_X(V ? 18 : 12));
    inOut(n, s, { y: 30 * U });
    const at = times(items, s, 0.45, 0.7);
    const bb = n.querySelectorAll(".bb"), bv = n.querySelectorAll(".bv");
    items.forEach((it, i) => {
      tl.to(bb[i], { scaleY: 1, duration: 0.5, ease: "power2.out" }, at[i]);
      tl.to(bv[i], { opacity: 1, duration: 0.15 }, at[i]);
    });
    TICK.push((t) => {
      if (t < s.t0 - 0.05 || t > s.t1 + 0.05) return;
      items.forEach((it, i) => {
        const u = o2(L.prog(t, at[i], 0.5));
        bv[i].textContent = L.figAt(it.value, u);
        bv[i].style.top = `${(base - hgt(it) * u - 54 * U).toFixed(0)}px`;       // the number rides the bar's top
      });
    });
    if (a) {
      const coAt = typeof s.calloutAt === "number" && s.calloutAt > at[at.length - 1] ? s.calloutAt : at[at.length - 1] + 0.7;
      tl.to(n.querySelector(".aw"), { attr: { "stroke-dashoffset": 0 }, duration: 0.35, ease: "power1.inOut" }, coAt);
      tl.to(n.querySelector(".ah"), { opacity: 1, duration: 0.1 }, coAt + 0.33);
      tl.fromTo(n.querySelector(".at"), { opacity: 0, scale: 0.8 }, { opacity: 1, scale: 1, duration: 0.25, ease: "back.out(2)" }, coAt + 0.2);
    }
  };

  // ------------------------------------------------------------------ waffle: 20 x 20, each square = 0.25%
  build.waffle = function (s) {
    const n = layer(true);
    const g = Math.round(V ? W * 0.52 : H * 0.5), pitch = g / 20, cell = pitch * 0.82;
    const k = s.frac > 0 ? Math.max(1, Math.min(400, Math.round(s.frac * 400))) : 0;
    let rows = "";
    for (let r = 0; r < 20; r++) {
      let cells = "";
      for (let c = 0; c < 20; c++) cells += `<div class="wc" style="position:absolute;left:${(c * pitch).toFixed(1)}px;top:0;width:${cell.toFixed(1)}px;height:${cell.toFixed(1)}px;background:#D6C9AA;border-radius:${(cell * 0.12).toFixed(1)}px"></div>`;
      rows += `<div class="wr" style="position:absolute;left:0;top:${(r * pitch).toFixed(1)}px;width:${g}px;height:${pitch.toFixed(1)}px;opacity:0">${cells}</div>`;
    }
    const label = `<div class="wl" style="opacity:0;${V ? `margin-top:${px(18)}` : `margin-left:${px(36)};align-self:center;max-width:${px(420)}`}">` +
      `<div class="wb" style="font:400 ${px(V ? 92 : 96)}/1 Anton;color:${C.red};white-space:nowrap">${esc(s.big)}</div>` +
      (s.small ? `<div style="font:800 ${px(V ? 28 : 28)}/1.25 Montserrat;color:${C.ink};margin-top:${px(8)}">${esc(s.small)}</div>` : "") + `</div>`;
    n.innerHTML = panel(kicker(s.head) + `<div style="display:flex;flex-direction:${V ? "column" : "row"}">` +
      `<div><div style="position:relative;width:${g}px;height:${g}px">${rows}</div>` +
      `<div style="font:700 ${px(17)} ${MONO};letter-spacing:2px;color:${C.muted};margin-top:${px(10)}">EACH SQUARE = 0.25%</div></div>${label}</div>` +
      (s.src ? `<div>${badge(s.src)}</div>` : ""), PANEL_X(V ? 16 : 12));
    inOut(n, s, { y: 30 * U });
    const wr = n.querySelectorAll(".wr"), wc = Array.from(n.querySelectorAll(".wc"));
    tl.to(wr, { opacity: 1, duration: 0.12, stagger: 0.045 }, s.t0 + 0.3);       // grid wipes in top to bottom, about 1 s
    const fillAt = Math.max(s.t0 + 1.35, typeof s.fillAt === "number" ? s.fillAt : 0);
    if (k) tl.to(wc.slice(0, k), { backgroundColor: C.red, duration: 0.08, stagger: Math.min(0.05, 1.0 / k) }, fillAt);
    const fillEnd = fillAt + (k ? Math.min(0.05, 1.0 / k) * k : 0);
    const labAt = typeof s.bigAt === "number" && s.bigAt >= s.t0 + 0.5 ? s.bigAt : fillEnd + 0.1;
    tl.fromTo(n.querySelector(".wl"), { opacity: 0, y: 14 * U }, { opacity: 1, y: 0, duration: 0.25, ease: "power2.out" }, labAt);
    // after the fill the red squares breathe, so the chart is never static
    if (k) TICK.push((t) => {
      if (t < fillEnd || t > s.t1 + 0.05) return;
      const b = 1 + 0.12 * Math.sin((t - fillEnd) * Math.PI);
      for (let i = 0; i < k; i++) wc[i].style.filter = `brightness(${b.toFixed(3)})`;
    });
  };

  // ------------------------------------------------------------------ balance bar: the whole, the sliver, the count-up
  build.balance = function (s) {
    const n = layer(true);
    const bw = Math.round(W * (V ? 0.7 : 0.6));
    const frac = Math.max(0.012, Math.min(1, s.frac || 0));
    const chips = (s.chips || []).map((c) => `<span class="bc" style="display:inline-block;margin:${px(10)} ${px(10)} 0 0;font:700 ${px(18)} ${MONO};letter-spacing:2px;` +
      `color:${C.ink};border:${px(2)} solid ${C.ink};border-radius:${px(6)};padding:${px(4)} ${px(8)};opacity:0">${esc(c.text)}</span>`).join("");
    n.innerHTML = panel(kicker(s.head) +
      `<div style="font:800 ${px(26)} Montserrat;color:${C.ink};margin-bottom:${px(10)}">${esc(s.label || "")}</div>` +
      `<div class="bo" style="position:relative;width:${bw}px;height:${px(76)};border:${px(4)} solid ${C.ink};border-radius:${px(12)};background:#fff;overflow:hidden;transform-origin:0 50%;transform:scaleX(0)">` +
      `<div class="bs" style="position:absolute;left:0;top:0;bottom:0;width:0;background:${C.red}"></div></div>` +
      `<div class="bn" style="font:400 ${px(V ? 96 : 92)}/1 Anton;color:${C.red};margin-top:${px(18)};white-space:nowrap;opacity:0">${esc(L.figAt(s.big, 0))}</div>` +
      (s.small ? `<div class="bt" style="display:inline-block;font:800 ${px(26)} Montserrat;color:#fff;background:${C.ink};padding:${px(6)} ${px(12)};border-radius:${px(6)};margin-top:${px(8)};opacity:0">${esc(s.small)}</div>` : "") +
      `<div>${chips}</div>` + (s.src ? `<div>${badge(s.src)}</div>` : ""), PANEL_X(V ? 22 : 18));
    inOut(n, s, { y: 30 * U });
    const q = (c) => n.querySelector(c);
    tl.to(q(".bo"), { scaleX: 1, duration: 0.5, ease: "power2.out" }, s.t0 + 0.3);
    const fillAt = typeof s.bigAt === "number" && s.bigAt >= s.t0 + 0.6 ? s.bigAt : s.t0 + 0.9;
    // the sliver fills as soon as the bar is drawn; the number still counts on its spoken word (dry run 4 review: an
    // empty bar sat 2.5 s waiting for the word)
    const sliverAt = Math.min(fillAt, s.t0 + 0.9);
    tl.to(q(".bs"), { width: `${(frac * 100).toFixed(2)}%`, duration: 0.6, ease: "power2.out" }, sliverAt);
    if (q(".bt")) tl.fromTo(q(".bt"), { opacity: 0, x: -20 * U }, { opacity: 1, x: 0, duration: 0.25 }, fillAt + 1.25);
    const cAt = times(s.chips || [], s, fillAt - s.t0 + 1.6, 0.6);
    n.querySelectorAll(".bc").forEach((c, i) => tl.fromTo(c, { opacity: 0, scale: 1.2 }, { opacity: 1, scale: 1, duration: 0.2 }, cAt[i]));
    const bn = q(".bn");
    tl.to(bn, { opacity: 1, duration: 0.15 }, fillAt);                 // no "₱0.00" on screen before the count starts
    const sl = q(".bs");
    TICK.push((t) => {
      if (t < s.t0 - 0.05 || t > s.t1 + 0.05) return;
      bn.textContent = L.figAt(s.big, o2(L.prog(t, fillAt, 1.2)));
      if (t > sliverAt + 0.6) sl.style.filter = `brightness(${(1 + 0.18 * Math.sin((t - sliverAt - 0.6) * Math.PI)).toFixed(3)})`;  // breathes
    });
  };

  // ------------------------------------------------------------------ date cards: pop about 2 s apart
  build.dates = function (s) {
    const n = layer(true);
    const items = (s.items || []).slice(0, 3);
    const cards = items.map((it, i) => {
      const c = col(it.color, i % 2 ? C.teal : C.red);
      return `<div class="dc" style="width:${px(V ? 280 : 270)};background:#fff;border:${px(4)} solid ${C.ink};border-radius:${px(16)};box-shadow:${px(7)} ${px(7)} 0 ${C.ink};overflow:hidden;opacity:0">` +
        `<div style="background:${c};color:#fff;font:700 ${px(22)} ${MONO};letter-spacing:3px;text-align:center;padding:${px(8)} 0">${esc(it.label)}</div>` +
        `<div style="font:400 ${px(V ? 120 : 112)}/1.05 Anton;color:${C.ink};text-align:center;margin-top:${px(8)}">${esc(it.big)}</div>` +
        `<div style="font:800 ${px(V ? 24 : 23)}/1.25 Montserrat;color:${C.ink};text-align:center;padding:${px(6)} ${px(14)} ${px(16)}">${esc(it.small)}</div></div>`;
    }).join("");
    n.innerHTML = `<div style="position:absolute;left:5%;right:${SAFE ? 14 : 5}%;top:${V ? 24 : 22}%;text-align:center">${kicker(s.head)}` +
      `<div style="display:flex;gap:${px(26)};justify-content:center;flex-wrap:wrap">${cards}</div>${s.src ? `<div style="text-align:center">${badge(s.src)}</div>` : ""}</div>`;
    tl.set(n, { opacity: 1 }, s.t0);
    tl.to(n, { opacity: 0, duration: 0.25 }, s.t1 - 0.25);
    const at = times(items, s, 0.2, 1.8);
    n.querySelectorAll(".dc").forEach((c, i) => tl.fromTo(c, { opacity: 0, scale: 0.9 }, { opacity: 1, scale: 1, duration: 0.25, ease: "back.out(2)" }, at[i]));
  };

  // ------------------------------------------------------------------ media card (+ side list, chips) over the map
  const ICON = {
    person: "M50 20 m-14 0 a14 14 0 1 0 28 0 a14 14 0 1 0 -28 0 M22 88 C22 62 36 52 50 52 C64 52 78 62 78 88",
    building: "M50 16 L84 40 H16 Z M24 46 V80 M40 46 V80 M60 46 V80 M76 46 V80 M16 84 H84 M12 90 H88",
    house: "M14 50 L50 18 L86 50 M24 42 V86 H76 V42 M42 86 V62 H58 V86",
    coins: "M24 72 a26 8 0 1 0 52 0 a26 8 0 1 0 -52 0 M24 72 v10 a26 8 0 0 0 52 0 v-10 M24 52 a26 8 0 1 0 52 0 a26 8 0 1 0 -52 0 M24 52 v10 a26 8 0 0 0 52 0 M24 32 a26 8 0 1 0 52 0 a26 8 0 1 0 -52 0 M24 32 v10 a26 8 0 0 0 52 0",
    document: "M28 12 H62 L76 26 V88 H28 Z M62 12 V26 H76 M38 42 H66 M38 54 H66 M38 66 H56",
    ballot: "M16 50 H84 V88 H16 Z M36 62 H64 M38 50 L44 14 H68 L62 50",
  };
  build.media = function (s) {
    const n = layer();
    const rows = (s.rows || []).slice(0, 4);
    const side = rows.length > 0;
    const cardW = Math.round(W * (V ? (side ? 0.44 : 0.56) : (side ? 0.36 : 0.36)));
    const cardH = Math.round(cardW * (V ? 1.25 : 0.8));
    const left = V ? (side ? W * 0.05 : (W - cardW) / 2) : (side ? W * 0.08 : (W - cardW) / 2);
    const top = H * (V ? 0.2 : 0.16);
    const icon = !s.src && (s.icon || "person");
    const inner = s.kind === "video" ? `<div class="vslot"></div>`
      : s.src ? `<img class="mi" src="${s.src}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:${s.focusPos || "50% 50%"}">`
        : `<div style="position:absolute;inset:0;background:${C.sheet}"></div><svg viewBox="0 0 100 100" style="position:absolute;left:18%;top:12%;width:64%;height:64%">` +
          `<path class="ic" d="${ICON[icon] || ICON.person}" fill="none" stroke="${C.ink}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100"/></svg>` +
          `<div style="position:absolute;left:0;right:0;top:80%;border-top:${px(3)} dashed ${C.muted}"></div>`;
    const lower = s.name ? `<div class="lt" style="position:absolute;left:${px(-10)};bottom:${px(22)};max-width:105%;opacity:0">` +
      `<div style="font:800 ${px(V ? 30 : 28)}/1.15 Montserrat;color:#fff;background:${C.ink};padding:${px(8)} ${px(14)}">${esc(s.name)}</div>` +
      (s.role ? `<div style="display:inline-block;font:700 ${px(V ? 19 : 18)} ${MONO};letter-spacing:1px;color:${C.ink};background:${C.yel};padding:${px(5)} ${px(12)}">${esc(s.role)}</div>` : "") + `</div>` : "";
    const chips = (s.chips || []).map((c, i) => `<div class="mc" style="position:absolute;left:${px(16)};top:${px(16 + i * 46)};font:700 ${px(V ? 19 : 18)} ${MONO};letter-spacing:2px;` +
      `color:${C.red};background:rgba(248,242,228,.95);border:${px(3)} solid ${C.red};border-radius:${px(6)};padding:${px(4)} ${px(10)};` +
      `max-width:calc(100% - ${px(52)});white-space:normal;line-height:1.25;opacity:0">${esc(c.text)}</div>`).join("");
    const credit = s.credit ? `<div style="font:700 ${px(15)}/1.3 ${MONO};letter-spacing:.5px;color:${C.muted};margin-top:${px(8)};max-width:${cardW}px">${esc(s.credit.toUpperCase())}</div>` : "";
    const list = side ? `<div style="position:absolute;left:${V ? (left + cardW + W * 0.04).toFixed(0) : (left + cardW + W * 0.04).toFixed(0)}px;right:${V ? "12%" : "8%"};top:${(top + 10 * U).toFixed(0)}px">` +
      rows.map((r) => `<div class="sl" style="margin-bottom:${px(16)};background:${C.sheet};border:${px(3)} solid ${r.color === "red" ? C.red : C.ink};` +
        `border-left:${px(12)} solid ${col(r.color, C.ink)};border-radius:${px(10)};padding:${px(12)} ${px(14)};font:800 ${px(V ? 27 : 27)}/1.22 Montserrat;` +
        `color:${r.color === "red" ? C.red : C.ink};box-shadow:${px(5)} ${px(5)} 0 ${C.ink};opacity:0">${esc(r.text)}</div>`).join("") + `</div>` : "";
    // the lower third sits on the photo frame and the credit line under it (dry run 3: they overlapped)
    n.innerHTML = `<div class="mcard" style="position:absolute;left:${left.toFixed(0)}px;top:${top.toFixed(0)}px;width:${cardW}px">` +
      `<div style="position:relative"><div class="mf" style="position:relative;width:${cardW}px;height:${cardH}px;overflow:hidden;border:${px(5)} solid ${C.ink};border-radius:${px(12)};` +
      `box-shadow:${px(9)} ${px(9)} 0 ${C.ink};background:#111">${inner}${chips}</div>${lower}</div>${credit}</div>${list}`;
    if (s.vid) { const v = document.getElementById(s.vid); if (v) n.querySelector(".vslot").replaceWith(v); }
    const card = n.querySelector(".mcard");
    tl.set(n, { opacity: 1 }, s.t0);
    tl.fromTo(card, { opacity: 0, x: -36 * U }, { opacity: 1, x: 0, duration: 0.4, ease: "power2.out" }, s.t0);
    tl.to(n, { opacity: 0, duration: 0.25 }, Math.max(s.t0 + 0.5, s.t1 - 0.25));
    const img = n.querySelector(".mi");
    if (img) tl.fromTo(img, { scale: 1.0 }, { scale: 1.1, duration: s.t1 - s.t0, ease: "none" }, s.t0);   // slow push inside the frame
    const ic = n.querySelector(".ic");
    if (ic) tl.to(ic, { attr: { "stroke-dashoffset": 0 }, duration: 0.9, ease: "power1.inOut" }, s.t0 + 0.2);
    const lt = n.querySelector(".lt");
    if (lt) tl.fromTo(lt, { opacity: 0, x: -24 * U }, { opacity: 1, x: 0, duration: 0.3, ease: "power2.out" }, s.t0 + 0.4);
    const rAt = times(rows, s, 0.7, 1.25);
    n.querySelectorAll(".sl").forEach((r, i) => tl.fromTo(r, { opacity: 0, x: 30 * U }, { opacity: 1, x: 0, duration: 0.3, ease: "power2.out" }, rAt[i]));
    const cAt = times(s.chips || [], s, 1.0, 0.8);
    n.querySelectorAll(".mc").forEach((c, i) => tl.fromTo(c, { opacity: 0, scale: 1.25 }, { opacity: 1, scale: 1, duration: 0.22, ease: "back.out(2)" }, cAt[i]));
  };

  // a per-frame drawer that throws must not stop the others (or the seek)
  const tick = (t) => { for (const f of TICK) { try { f(t); } catch (e) { console.error("atlas tick", e); } } };
  return { stamp, tags, tick, ticks: () => TICK.length };
};
