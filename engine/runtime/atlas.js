/* TFS "Built to Fail" atlas runtime. Builds a whole video from window.SPEC and registers ONE paused GSAP
 * timeline under window.__timelines[SPEC.id] for HyperFrames to seek frame by frame. Deterministic: no clocks,
 * no randomness.
 *
 * SPEC = {id, width, height, duration, geo: {world:"<path d>", ph:"<d>", phProv:"<d>", nz:"<d>", views:{name:[x,y,w,h]}},
 *         shots: [{t0, t1, k, ...}], words: [{w, t0, t1, brk}]}
 * Shot kinds: map, bigtext, title, doc, cards, bars, timeline, compare, seats, split, broll; the v3 blocks (globe,
 * checklist, linechart, barchart, waffle, balance, dates, media, and a `stamp` on any shot) live in atlas_blocks.js
 * and per-frame helpers in atlas_lib.js, both loaded before this file. Caption words with `key` get a filled box.
 */
(function () {
  const S = window.SPEC, W = S.width, H = S.height, V = H > W * 1.3;
  const U = Math.min(W, H) / 1080 * (V ? 1.25 : 1.35);  // 1 unit = 1 px at 1080 short side; wide frames read from further away
  const C = { paper: "#EFE6D2", ink: "#1B2430", red: "#C8102E", teal: "#0F766E", yel: "#FCD116", muted: "#6b5a3f", sheet: "#F8F2E4" };
  const stage = document.getElementById("stage");
  const tl = gsap.timeline({ paused: true });
  const esc = (t) => String(t ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const px = (n) => `${Math.round(n * U)}px`;

  function el(tag, style, html, parent) {
    const e = document.createElement(tag);
    if (style) e.setAttribute("style", style);
    if (html !== undefined) e.innerHTML = html;
    (parent || stage).appendChild(e);
    return e;
  }

  // ------------------------------------------------------------------ base: paper, grain, persistent atlas map
  stage.style.background = C.paper;
  // v2: real paper texture with fold creases (textures/paper.jpg, made by make_textures.py), soft vignette on top
  el("div", `position:absolute;inset:0;background:url(textures/paper${V ? "_v" : ""}.jpg) center/cover`);
  el("div", "position:absolute;inset:0;background:radial-gradient(ellipse at 50% 40%,rgba(255,255,255,.18),rgba(120,90,50,.20))");
  el("div", "position:absolute;width:0;height:0", `<svg width="0" height="0"><filter id="grain"><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="4" stitchTiles="stitch"/>` +
    `<feColorMatrix values="0 0 0 0 .35 0 0 0 0 .28 0 0 0 0 .18 0 0 0 .5 0"/></filter></svg>`);

  const G = S.geo;
  const v0 = G.views.ph;
  const mapWrap = el("div", "position:absolute;inset:0;opacity:0");
  mapWrap.innerHTML =
    `<svg id="atlas" width="${W}" height="${H}" viewBox="${v0.join(" ")}" preserveAspectRatio="xMidYMid meet">` +
    `<g stroke="#C9B691" stroke-width="${G.grid.w}" stroke-dasharray="${G.grid.dash}" fill="none">${G.grid.d}</g>` +
    `<path d="${G.world}" fill="#E2D3B3" stroke="#C3AE86" stroke-width="${G.stroke}"/>` +
    `<path id="phProv" d="${G.phProv}" fill="${C.red}" fill-opacity="0" stroke="#7a0b1d" stroke-opacity="0" stroke-width="${G.stroke * 0.8}"/>` +
    `<path id="phLine" d="${G.ph}" fill="none" stroke="${C.red}" stroke-width="${G.stroke * 3}" stroke-linejoin="round"/>` +
    `<path id="nzFill" d="${G.nz}" fill="${C.teal}" fill-opacity="0" stroke="${C.teal}" stroke-width="${G.stroke * 2}" stroke-opacity="0"/>` +
    `</svg>`;
  const grain = el("div", "position:absolute;inset:0;filter:url(#grain);opacity:.35;pointer-events:none");
  const phLine = mapWrap.querySelector("#phLine");
  const L = phLine.getTotalLength();
  phLine.setAttribute("stroke-dasharray", `${L} ${L}`);
  // an instant opener (the Short's first frame is its feed thumbnail) starts with the map already traced and filled
  const OPEN = (S.shots || []).find((s) => s.k === "map" && s.instant && s.t0 <= 0.001);
  phLine.setAttribute("stroke-dashoffset", OPEN ? "0" : `${L}`);
  if (OPEN && OPEN.fill === "ph") {
    const pv = mapWrap.querySelector("#phProv");
    pv.setAttribute("fill-opacity", "0.85");
    pv.setAttribute("stroke-opacity", "1");
  }
  mapWrap.style.opacity = OPEN ? "1" : "0";
  tl.set(mapWrap, { opacity: OPEN ? 1 : 0 }, 0);

  const layer = (backdrop) => { const n = el("div", "position:absolute;inset:0;opacity:0");
    if (backdrop) n.dataset.bd = "1";              // the paper backdrop is added after the shot's HTML is set
    return n; };
  function inOut(node, s, from) {
    // the opening shot is fully on screen at 0.0 s: the first frame is the Short's thumbnail in the feed
    if (s.instant) tl.set(node, { opacity: 1, y: 0, x: 0, scale: 1 }, s.t0);
    else tl.fromTo(node, Object.assign({ opacity: 0 }, from || { y: 30 * U }), { opacity: 1, y: 0, x: 0, scale: 1, duration: 0.35, ease: "power2.out" }, s.t0);
    tl.to(node, { opacity: 0, duration: 0.25, ease: "power1.in" }, Math.max(s.t0 + 0.4, s.t1 - 0.25));
  }
  const badge = (txt) => txt ? `<div style="display:inline-block;margin-top:${px(18)};font:700 ${px(V ? 24 : 27)} 'Segoe UI',sans-serif;letter-spacing:.5px;color:${C.muted};max-width:${Math.round(W * (V ? 0.84 : 0.62))}px;white-space:normal;line-height:1.3;` +
    `background:${C.sheet};border:${px(2)} solid ${C.muted};border-radius:${px(8)};padding:${px(6)} ${px(12)}">SOURCE: ${esc(txt)}</div>` : "";
  const centerBox = `position:absolute;left:50%;top:${V ? "34%" : "47%"};transform:translate(-50%,-50%);width:${V ? 88 : 72}%;text-align:center`;

  // ------------------------------------------------------------------ shot builders
  const build = {
    map(s) {
      if (s.instant) tl.set(mapWrap, { opacity: 1 }, s.t0); else tl.to(mapWrap, { opacity: 1, duration: 0.4 }, s.t0);
      if (s.view) tl.to("#atlas", { attr: { viewBox: G.views[s.view].join(" ") }, duration: s.move || 1.6, ease: "power2.inOut" }, s.t0);
      if (s.draw && s.instant) tl.set(phLine, { attr: { "stroke-dashoffset": 0 } }, s.t0);
      else if (s.draw) tl.to(phLine, { attr: { "stroke-dashoffset": 0 }, duration: s.draw, ease: "power1.inOut" }, s.t0);
      if (s.fill === "ph" && s.instant) tl.set("#phProv", { attr: { "fill-opacity": 0.85, "stroke-opacity": 1 } }, s.t0);
      else if (s.fill === "ph") tl.to("#phProv", { attr: { "fill-opacity": 0.85, "stroke-opacity": 1 }, duration: 0.6 }, s.t0 + 0.3);
      if (s.fill === "nz") tl.to("#nzFill", { attr: { "fill-opacity": 0.85, "stroke-opacity": 1 }, duration: 0.6 }, s.t0 + 0.6);
      if (s.label) {
        const n = layer();
        n.innerHTML = `<div style="position:absolute;${s.labelPos || `left:6%;top:${V ? 60 : 70}%`};font:800 ${px(V ? 40 : 34)} Montserrat;color:${C.ink};background:${C.yel};` +
          `padding:${px(10)} ${px(18)};border-radius:${px(8)};box-shadow:${px(5)} ${px(5)} 0 ${C.ink}">${esc(s.label)}</div>`;
        inOut(n, Object.assign({}, s, { t0: s.t0 + (s.labelDelay || 0) }), { x: -40 * U });
      }
      if (s.hide) tl.to(mapWrap, { opacity: 0, duration: 0.4 }, s.t1 - 0.4);
    },
    bigtext(s) {
      const n = layer();
      n.innerHTML = `<div style="${centerBox}"><div style="display:inline-block;background:${C.sheet};border:${px(4)} solid ${C.ink};border-radius:${px(18)};box-shadow:${px(8)} ${px(8)} 0 ${C.ink};padding:${px(26)} ${px(40)}">` +
        `<div style="font:400 ${px(V ? 96 : 72)}/1.05 Anton;color:${C.ink};letter-spacing:1px">${esc(s.text)}</div>` +
        (s.sub ? `<div style="font:800 ${px(28)} Montserrat;color:${C.red};margin-top:${px(14)};letter-spacing:2px">${esc(s.sub)}</div>` : "") + `</div>` +
        (s.src ? `<div>${badge(s.src)}</div>` : "") + `</div>`;
      inOut(n, s, { scale: 0.92 });
    },
    title(s) {
      const n = layer();
      if (s.mat) {                                     // v2 chapter card: numbered paper card on a cutting mat
        n.innerHTML = `<div style="position:absolute;inset:0;background:url(textures/mat${V ? "_v" : ""}.jpg) center/cover"></div>` +
          `<div class="card" style="position:absolute;left:50%;top:${V ? 40 : 50}%;width:${V ? 86 : 68}%;transform:translate(-50%,-50%) rotate(-2.5deg);` +
          `background:url(textures/paper.jpg) center/cover;box-shadow:0 ${px(22)} ${px(40)} rgba(0,0,0,.45);padding:${px(46)} ${px(56)};text-align:left;` +
          `display:flex;align-items:flex-start;gap:${px(44)}"><div style="flex:1;min-width:0">` +   // number gets its own column: it can never sit on the title
          (s.kicker ? `<div style="font:800 ${px(26)} Montserrat;letter-spacing:6px;color:${C.red}">${esc(s.kicker)}</div>` : "") +
          `<div style="font:400 ${px(V ? 96 : 88)}/1.02 Anton;color:${C.ink};margin-top:${px(10)}">${s.html || esc(s.text)}</div></div>` +
          (s.num ? `<div class="cnum" style="flex:none;font:400 ${px(120)}/0.9 Anton;color:${C.red};opacity:.9;margin-top:${px(-6)}">${esc(s.num)}</div>` : "") + `</div>`;
        inOut(n, s, { y: 80 * U });
        tl.fromTo(n.querySelector(".card"), { rotation: -7 }, { rotation: -2.5, duration: 0.6, ease: "back.out(1.4)" }, s.t0);
        return;
      }
      n.innerHTML = `<div style="position:absolute;inset:0;background:${C.ink}"></div><div style="${centerBox};color:#fff">` +
        (s.kicker ? `<div style="font:800 ${px(26)} Montserrat;letter-spacing:6px;color:${C.yel}">${esc(s.kicker)}</div>` : "") +
        `<div style="font:400 ${px(V ? 104 : 96)}/1.02 Anton;margin-top:${px(14)}">${s.html || esc(s.text)}</div></div>`;
      inOut(n, s, { scale: 1.06 });
    },
    broll(s) {                                         // v2: real photo (slow push) or video clip, graded, word and credit on top
      const n = layer();
      const media = s.kind === "video" ? `<div class="vslot"></div>`
        : `<img class="bi" src="${s.src}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:${s.focus || "50% 50%"}">`;
      const gate = s.gate ? `<div style="position:absolute;inset:0;box-shadow:inset 0 0 0 ${px(26)} #0b0b0b, inset 0 0 ${px(90)} ${px(40)} rgba(0,0,0,.75);border-radius:${px(18)}"></div>` +
        `<div style="position:absolute;inset:0;filter:url(#grain);opacity:.55"></div>` : "";
      const word = s.word ? `<div class="bw" style="position:absolute;left:${V ? 7 : 5}%;top:${V ? 52 : 62}%;font:400 ${px(V ? 64 : 76)}/1 Anton;color:${C.paper};letter-spacing:1px;` +
        `background:rgba(140,20,25,.82);padding:${px(10)} ${px(22)};border-radius:${px(10)};box-shadow:${px(6)} ${px(6)} 0 rgba(15,20,32,.8)">${esc(s.word)}</div>` : "";
      const credit = s.credit ? `<div style="position:absolute;right:${px(22)};top:${px(20)};font:700 ${px(V ? 20 : 19)} 'Segoe UI',sans-serif;color:#fff;` +
        `background:rgba(15,20,32,.7);padding:${px(5)} ${px(12)};border-radius:${px(6)}">${esc(s.credit)}</div>` : "";
      n.innerHTML = `<div style="position:absolute;inset:0;background:#111"></div>${media}${gate}${word}${credit}`;
      if (s.vid) {                                     // move the static video into this layer, under the gate, word and credit
        const v = document.getElementById(s.vid);
        if (v) n.querySelector(".vslot").replaceWith(v);
      }
      if (s.instant) tl.set(n, { opacity: 1 }, s.t0); else tl.fromTo(n, { opacity: 0 }, { opacity: 1, duration: 0.25 }, s.t0);
      tl.to(n, { opacity: 0, duration: 0.2 }, Math.max(s.t0 + 0.3, s.t1 - 0.2));
      const img = n.querySelector(".bi");
      if (img) tl.fromTo(img, { scale: 1.0, xPercent: 0 }, { scale: 1.12, xPercent: s.pan || -2, duration: s.t1 - s.t0, ease: "none" }, s.t0);
      const w = n.querySelector(".bw");
      if (w) tl.fromTo(w, { opacity: 0, x: -40 * U }, { opacity: 1, x: 0, duration: 0.3, ease: "power2.out" }, s.t0 + 0.3);
    },
    doc(s) {
      const n = layer();
      let body = esc(s.body);
      (s.hl || []).forEach((h, i) => { body = body.replace(esc(h), `<span class="hl hl${i}" style="background-size:0% 100%">${esc(h)}</span>`); });
      const long = s.body.length > 260;                  // long quotes get smaller type so the card clears the captions
      n.innerHTML = `<div style="position:absolute;left:50%;top:${V ? 34 : (long ? 44 : 48)}%;width:${V ? 86 : (long ? 62 : 56)}%;transform:translate(-50%,-50%) rotate(-1.5deg);background:${C.sheet};` +
        `box-shadow:0 ${px(18)} ${px(40)} rgba(60,40,20,.35);padding:${px(54)} ${px(60)}">` +
        `<div style="font:700 ${px(18)} 'Segoe UI';letter-spacing:4px;color:${C.muted};text-align:center">${esc(s.head)}</div>` +
        `<div style="text-align:center;margin:${px(12)} 0 ${px(26)}"><span style="position:relative;display:inline-block;font:800 ${px(30)} Montserrat;color:${C.red};letter-spacing:3px;padding:${px(6)} ${px(18)}">${esc(s.sec)}` +
        `<svg class="ring" viewBox="0 0 100 40" preserveAspectRatio="none" style="position:absolute;left:-6%;top:-30%;width:112%;height:160%;overflow:visible">` +
        `<path d="M 8 22 C 6 6, 70 2, 92 12 C 102 20, 88 36, 50 37 C 18 38, 2 30, 10 14" fill="none" stroke="${C.red}" stroke-width="${px(3.5)}" stroke-linecap="round" vector-effect="non-scaling-stroke" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100"/></svg></span></div>` +
        `<div style="font:400 ${px(V ? (long ? 30 : 36) : (long ? 25 : 32))}/1.5 Georgia,serif;color:#262019">${body}</div>${badge(s.src)}</div>`;
      n.querySelectorAll(".hl").forEach((h) => h.setAttribute("style", `background-image:linear-gradient(${C.yel},${C.yel});background-repeat:no-repeat;background-position:0 70%;background-size:0% 70%;padding:0 ${px(3)}`));
      inOut(n, s, { y: 60 * U, rotation: -4 });
      tl.to(n.querySelector(".ring path"), { attr: { "stroke-dashoffset": 0 }, duration: 0.6, ease: "power1.inOut" }, s.t0 + 0.35);   // hand-drawn circle
      (s.hl || []).forEach((h, i) => tl.to(n.querySelectorAll(".hl")[i], { backgroundSize: "100% 70%", duration: 0.7, ease: "power1.inOut" },
        s.t0 + 0.5 + i * Math.max(0.8, (s.t1 - s.t0 - 1.2) / Math.max(1, s.hl.length))));
    },
    cards(s) {
      const n = layer(true);
      const items = s.items.map((it, i) => `<div class="cd cd${i}" style="background:${C.sheet};border:${px(4)} solid ${C.ink};border-radius:${px(18)};box-shadow:${px(8)} ${px(8)} 0 ${C.ink};` +
        `padding:${px(22)} ${px(30)};${V ? "" : "flex:1"}"><div style="font:400 ${px(V ? 78 : 70)}/1 Anton;color:${it.color === "teal" ? C.teal : it.color === "ink" ? C.ink : C.red}">${esc(it.big)}</div>` +
        `<div style="font:800 ${px(V ? 30 : 26)}/1.25 Montserrat;color:${C.ink};margin-top:${px(10)}">${esc(it.small)}</div></div>`).join("");
      n.innerHTML = `<div style="position:absolute;left:6%;right:6%;top:${V ? 22 : 30}%;display:flex;flex-direction:${V ? "column" : "row"};gap:${px(28)}">${items}</div>` +
        `<div style="position:absolute;left:6%;top:${V ? 60 : 70}%">${badge(s.src)}</div>`;
      tl.set(n, { opacity: 1 }, s.t0);
      s.items.forEach((_, i) => tl.fromTo(n.querySelectorAll(".cd")[i], { opacity: 0, y: 50 * U }, { opacity: 1, y: 0, duration: 0.35, ease: "back.out(1.6)" },
        s.t0 + i * Math.max(0.5, (s.t1 - s.t0 - 1) / s.items.length)));
      tl.to(n, { opacity: 0, duration: 0.25 }, s.t1 - 0.25);
    },
    bars(s) {
      const n = layer(true);
      // the value sits on the label line, never inside the bar (dry run: long values overflowed the fill)
      const rows = s.items.map((it, i) => `<div style="margin-bottom:${px(34)}"><div style="display:flex;justify-content:space-between;align-items:baseline;gap:${px(20)};margin-bottom:${px(10)}">` +
        `<div style="font:800 ${px(30)} Montserrat;color:${C.ink}">${esc(it.label)}</div>` +
        `<div style="font:400 ${px(V ? 44 : 40)} Anton;color:${it.color === "teal" ? C.teal : C.red};white-space:nowrap">${esc(it.value)}</div></div>` +
        `<div style="position:relative;height:${px(46)};background:#fff;border:${px(3)} solid ${C.ink};border-radius:${px(10)};overflow:hidden">` +
        `<div class="bf bf${i}" style="position:absolute;left:0;top:0;bottom:0;width:0;background:${it.color === "teal" ? C.teal : C.red}"></div></div></div>`).join("");
      n.innerHTML = `<div style="position:absolute;left:8%;right:8%;top:${V ? 24 : 26}%">${rows}${badge(s.src)}</div>`;
      inOut(n, s);
      s.items.forEach((it, i) => tl.to(n.querySelectorAll(".bf")[i], { width: `${it.frac * 100}%`, duration: 0.9, ease: "power2.out" },
        s.t0 + 0.4 + i * Math.max(0.6, (s.t1 - s.t0 - 1.2) / s.items.length)));
    },
    timeline(s) {
      const n = layer(true);
      const it = s.items.map((x, i) => `<div class="ti ti${i}" style="display:flex;gap:${px(24)};align-items:flex-start;margin-bottom:${px(26)}">` +
        `<div style="flex:none;font:400 ${px(34)} Anton;color:#fff;background:${C.ink};padding:${px(6)} ${px(14)};border-radius:${px(6)}">${esc(x.date)}</div>` +
        `<div style="font:800 ${px(30)}/1.25 Montserrat;color:${C.ink};padding-top:${px(4)}">${esc(x.text)}</div></div>`).join("");
      n.innerHTML = `<div style="position:absolute;left:8%;right:8%;top:${V ? 20 : 20}%"><div style="border-left:${px(6)} solid ${C.red};padding-left:${px(30)}">${it}</div>` +
        (s.foot ? `<div style="font:400 ${px(54)}/1.1 Anton;color:${C.red};margin-top:${px(20)}">${esc(s.foot).split("\n").join("<br>")}</div>` : "") + `${badge(s.src)}</div>`;
      tl.set(n, { opacity: 1 }, s.t0);
      s.items.forEach((_, i) => tl.fromTo(n.querySelectorAll(".ti")[i], { opacity: 0, x: -40 * U }, { opacity: 1, x: 0, duration: 0.35 },
        s.t0 + i * Math.max(0.6, (s.t1 - s.t0 - 1.5) / (s.items.length + (s.foot ? 1 : 0)))));
      tl.to(n, { opacity: 0, duration: 0.25 }, s.t1 - 0.25);
    },
    compare(s) {
      const n = layer(true);
      const card = (c, col) => `<div style="flex:1;background:${C.sheet};border:${px(4)} solid ${C.ink};border-radius:${px(20)};box-shadow:${px(8)} ${px(8)} 0 ${C.ink};padding:${px(26)} ${px(30)}">` +
        `<div style="font:800 ${px(24)} Montserrat;letter-spacing:4px;color:${col}">${esc(c.name)}</div><div style="font:400 ${px(V ? 92 : 86)}/1 Anton;color:${col};margin:${px(8)} 0">${esc(c.big)}</div>` +
        `<div style="font:800 ${px(26)}/1.3 Montserrat;color:${C.ink}">${esc(c.small)}</div></div>`;
      n.innerHTML = `<div style="position:absolute;left:6%;right:6%;top:${V ? 20 : 26}%;display:flex;flex-direction:${V ? "column" : "row"};gap:${px(30)};align-items:stretch">` +
        `${card(s.ph, C.red)}<div style="align-self:center;font:400 ${px(54)} Anton;color:${C.ink}">VS</div>${card(s.nz, C.teal)}</div>` +
        `<div style="position:absolute;left:6%;top:${V ? 60 : 70}%">${badge(s.src)}</div>`;
      inOut(n, s, { scale: 0.95 });
    },
    seats(s) {
      const n = layer(true);
      const dots = (k, total, col) => Array.from({ length: total }, (_, i) => `<span style="display:inline-block;width:${px(V ? 26 : 22)};height:${px(V ? 26 : 22)};margin:${px(3)};border-radius:50%;` +
        `background:${i < k ? col : "#D6C9AA"}"></span>`).join("");
      const rows = s.items.map((it, i) => `<div class="sr sr${i}" style="margin-bottom:${px(30)}"><div style="font:800 ${px(30)} Montserrat;color:${C.ink};margin-bottom:${px(8)}">${esc(it.label)}</div>` +
        `<div style="width:${px(V ? 900 : 1000)};line-height:0">${dots(it.value, it.of, it.color === "ink" ? C.ink : it.color === "teal" ? C.teal : C.red)}</div></div>`).join("");
      n.innerHTML = `<div style="position:absolute;left:7%;top:${V ? 20 : 18}%">${rows}${badge(s.src)}</div>`;
      tl.set(n, { opacity: 1 }, s.t0);
      s.items.forEach((_, i) => tl.fromTo(n.querySelectorAll(".sr")[i], { opacity: 0, y: 30 * U }, { opacity: 1, y: 0, duration: 0.4 },
        s.t0 + i * Math.max(0.8, (s.t1 - s.t0 - 1) / s.items.length)));
      tl.to(n, { opacity: 0, duration: 0.25 }, s.t1 - 0.25);
    },
    split(s) {
      const n = layer();
      n.innerHTML = `<div style="position:absolute;left:0;top:0;bottom:0;width:50%;background:${C.red}"></div><div style="position:absolute;right:0;top:0;bottom:0;width:50%;background:${C.teal}"></div>` +
        `<div style="position:absolute;left:4%;top:${V ? 21 : 12}%;width:42%;color:#fff;font:400 ${px(V ? 60 : 64)}/1.05 Anton">${esc(s.left)}</div>` +
        `<div style="position:absolute;left:54%;top:${V ? 21 : 12}%;width:42%;color:#fff;font:400 ${px(V ? 60 : 64)}/1.05 Anton">${esc(s.right)}</div>` +
        (s.text ? `<div style="position:absolute;left:50%;top:${V ? 46 : 64}%;transform:translateX(-50%);background:${C.paper};padding:${px(16)} ${px(30)};border-radius:${px(12)};` +
          `font:400 ${px(V ? 70 : 72)}/1.05 Anton;color:${C.ink};${V ? "width:80%;white-space:normal;text-align:center" : "white-space:nowrap"}">${esc(s.text)}</div>` : "") +
        (s.src ? `<div style="position:absolute;left:4%;top:${V ? 58 : 72}%">${badge(s.src)}</div>` : "");
      inOut(n, s, { scale: 1.04 });
    },
  };
  const X = window.TFS_BLOCKS ? window.TFS_BLOCKS({ W, H, V, U, C, tl, el, esc, px, layer, inOut, badge, build, globe: G.globe }) : null;
  for (const s of S.shots) {
    (build[s.k] || (() => { throw new Error("unknown shot " + s.k); }))(s);
    if (X && s.stamp) X.stamp(s);
  }
  document.querySelectorAll("[data-bd]").forEach((n) => n.insertAdjacentHTML("afterbegin", `<div style="position:absolute;inset:0;background:rgba(239,230,210,.9)"></div>`));

  // ------------------------------------------------------------------ karaoke captions (word-timed)
  if (S.words && S.words.length) {
    // captions stay inside a 7% side margin and wrap rather than run off-frame; Shorts sit at 72%, above the UI
    const capBox = el("div", `position:absolute;left:7%;right:7%;top:${V ? 72 : 86}%;text-align:center;z-index:9`);
    let group = [];
    const groups = [];
    const MAXC = V ? 26 : 44;                       // characters per caption line, so a line never wraps
    S.words.forEach((w, i) => {
      const len = group.reduce((n, x) => n + x.w.length + 1, 0);
      if (group.length && len + w.w.length > MAXC) { groups.push(group); group = []; }
      group.push(w);
      if (w.brk || i === S.words.length - 1) { groups.push(group); group = []; }
    });
    groups.forEach((g, gi) => {
      // no box (Bryce, 2026-11-24): white letters with a thin dark outline and a soft shadow around the letters only
      const o = Math.max(2, Math.round((V ? 2.4 : 2.6) * U));               // outline thickness in px
      const ring = [[1, 0], [-1, 0], [0, 1], [0, -1], [0.7, 0.7], [-0.7, 0.7], [0.7, -0.7], [-0.7, -0.7]]
        .map(([dx, dy]) => `${(dx * o).toFixed(1)}px ${(dy * o).toFixed(1)}px 0 rgba(15,20,32,.92)`).join(",");
      const line = el("div", `position:absolute;left:0;right:0;margin:0 auto;width:fit-content;max-width:100%;white-space:nowrap;opacity:0;font:800 ${px(V ? 34 : 38)}/1.2 Montserrat;color:#fff;` +
        `text-shadow:${ring},0 ${px(3)} ${px(10)} rgba(0,0,0,.45);padding:${px(4)} ${px(8)}`, "", capBox);
      line.innerHTML = g.map((w, j) => `<span class="w${j}"${w.key ? ` style="display:inline-block;padding:0 ${px(9)};border-radius:${px(8)}"` : ""}>${esc(w.w)}</span>`).join(" ");
      const end = gi + 1 < groups.length ? Math.min(groups[gi + 1][0].t0, g[g.length - 1].t1 + 0.6) : g[g.length - 1].t1 + 0.6;
      tl.set(line, { opacity: 1 }, g[0].t0);
      tl.set(line, { opacity: 0 }, end);
      g.forEach((w, j) => {
        const sp = line.querySelectorAll("span")[j];
        if (w.key) {                               // key word: a filled box in TFS red (gold for numbers) that stays up
          const num = /[0-9₱%]/.test(w.w);
          tl.set(sp, { backgroundColor: num ? C.yel : C.red, color: num ? C.ink : "#fff", textShadow: "none" }, w.t0);
          tl.fromTo(sp, { scale: 1.18 }, { scale: 1, duration: 0.18, ease: "back.out(2)", immediateRender: false }, w.t0);
          return;
        }
        tl.set(sp, { color: C.yel }, w.t0);
        tl.set(sp, { color: "#fff" }, w.t1 + 0.02);
      });
    });
  }

  // slow camera drift so no shot ever holds still (TFS rule: no freeze over 2 s): everything already on the stage
  // moves into one camera layer that breathes 1.0 to 1.035 every 6 s
  const cam = document.createElement("div");
  cam.setAttribute("style", `position:absolute;inset:0;transform-origin:50% 45%`);
  while (stage.firstChild) cam.appendChild(stage.firstChild);
  stage.appendChild(cam);
  if (V) {                                         // Reels/Shorts/TikTok watermark: outside the camera so it never moves; top-left of
    const wm = document.createElement("div");      // the platform safe zone (y 360 to 1420, clear of the right-side buttons)
    const o = [[2, 0], [-2, 0], [0, 2], [0, -2], [1.4, 1.4], [-1.4, 1.4], [1.4, -1.4], [-1.4, -1.4]].map(([x, y]) => `${x}px ${y}px 0 rgba(15,20,32,.85)`).join(",");
    wm.setAttribute("style", `position:absolute;left:${0.06 * W}px;top:${0.125 * H}px;display:flex;align-items:center;gap:${0.012 * W}px;opacity:.9;pointer-events:none`);
    wm.innerHTML = `<img src="textures/tfs_logo.png" style="width:${0.058 * W}px;height:${0.058 * W}px;border-radius:50%;box-shadow:0 2px 8px rgba(0,0,0,.45)">` +
      `<div style="font:800 ${0.027 * W}px Montserrat;color:#fff;letter-spacing:.5px;text-shadow:${o},0 3px 8px rgba(0,0,0,.4)">@thefilipinostandard</div>`;
    stage.appendChild(wm);
  }
  for (let t = 0, k = 0; t < S.duration; t += 6, k++) {
    tl.to(cam, { scale: k % 2 ? 1.0 : 1.035, x: (k % 2 ? 1 : -1) * 6 * U, duration: Math.min(6, S.duration - t), ease: "sine.inOut" }, t);
  }
  if (X && X.ticks()) {                            // per-frame drawing (globe, count-ups) as a pure function of time, driven
    const clock = { v: 0, t(x) { if (x === undefined) return this.v; this.v = x; X.tick(x); } };   // by a setter tween:
    tl.fromTo(clock, { t: 0 }, { t: S.duration, duration: S.duration, ease: "none", lazy: false }, 0);  // seek-safe
  }
  tl.set({}, {}, S.duration);
  window.__timelines = window.__timelines || {};
  window.__timelines[S.id] = tl;
})();
