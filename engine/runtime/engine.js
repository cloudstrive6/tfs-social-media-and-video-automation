/* The Filipino Standard vector engine: builds a whole video from window.SPEC and registers ONE paused GSAP
 * timeline under window.__timelines[SPEC.id] for HyperFrames to seek frame by frame. Everything is
 * deterministic (seeded variety, no clocks), as HyperFrames requires. Captions and audio are added afterwards
 * by the Python pipeline (FFmpeg), so this renders picture only.
 *
 * SPEC = {id, width, height, duration, look: "flat"|"doodle", emoji: {key: "<svg…>"},
 *         scenes: [{start, dur, kind: "scene"|"card", background, camera, actors[], props[], bubbles[],
 *                   mouth: [[t0, t1], …] (speaking actor's words, seconds from scene start), card}]}
 */
(function () {
  const S = window.SPEC;
  const W = S.width, H = S.height, VERTICAL = H > W * 1.3;
  const { puppet, POSES, rng } = window.TFS_PUPPETS;
  const { background, GROUND } = window.TFS_BACKGROUNDS;
  const stage = document.getElementById("stage");
  const tl = gsap.timeline({ paused: true });
  const SCALE = Math.max(W, H) / 1000;                      // background box (1000x1000) -> pixels
  // the ground line sits at 80% of the frame when the set allows it (wide frames would otherwise be 40% floor);
  // tall frames keep the set's own ground. The set is placed so its ground lands exactly there.
  const GROUND_PX = Math.max(H - (1000 - GROUND) * SCALE, Math.min(H * 0.8, GROUND * SCALE));
  const BG_BOX = `position:absolute;left:${(W - 1000 * SCALE) / 2}px;top:${GROUND_PX - GROUND * SCALE}px`;
  const SAFE = VERTICAL ? { x0: 0.05 * W, x1: 0.85 * W, y0: 0.07 * H, y1: 0.58 * H }   // clear of UI + captions
                        : { x0: 0.05 * W, x1: 0.95 * W, y0: 0.06 * H, y1: 0.94 * H };
  const esc = (t) => String(t || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  function el(tag, attrs, html) {
    const e = document.createElement(tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (html !== undefined) e.innerHTML = html;
    return e;
  }

  // ------------------------------------------------------------------ doodle look (hand-drawn wobble, boiling)
  if (S.look === "doodle") {
    stage.appendChild(el("div", { style: "position:absolute;width:0;height:0" },
      `<svg width="0" height="0"><filter id="doodle"><feTurbulence id="doodleNoise" type="fractalNoise" baseFrequency="0.018" numOctaves="2" seed="1"/>` +
      `<feDisplacementMap in="SourceGraphic" scale="5"/></filter></svg>`));
    for (let t = 0, k = 1; t < S.duration; t += 1 / 8, k = (k % 3) + 1) {   // "boil" at 8 fps like hand animation
      tl.set("#doodleNoise", { attr: { seed: k } }, t);
    }
  }

  // ------------------------------------------------------------------ actors
  function placeActor(scene, a, i, layer) {
    // the back row is a step further away: a little smaller and higher, still clearly a grown-up
    const hPx = a.scale * H * (a.row === "back" ? 0.9 : 1);
    const wPx = hPx / 2;
    const bottom = GROUND_PX - (a.row === "back" ? 0.03 * H : 0) + 0.01 * H;
    const x = a.x * W - wPx / 2;
    const flip = a.facing === "left" ? "scale(-1 1) translate(-300 0)" : "";
    const box = el("div", { class: "actor", style: `position:absolute;left:${x}px;top:${bottom - hPx}px;width:${wPx}px;height:${hPx}px;` +
      `z-index:${a.row === "back" ? 2 : 3}` });
    box.innerHTML = `<svg viewBox="0 0 300 600" width="${wPx}" height="${hPx}" overflow="visible"><g transform="${flip}">` +
      puppet({ who: a.who, expression: a.expression, seed: a.seed || (i + 1) * 7, label: "" }) + `</g></svg>`;
    if (a.label) {                                          // never mirrored with the figure, never off-frame
      const fs = Math.max(14, wPx * 0.085);
      box.appendChild(el("div", { class: "tag", style: `position:absolute;left:${-wPx * 0.1}px;width:${wPx * 1.2}px;top:${hPx * 0.44}px;` +
        `text-align:center;font:800 ${fs}px Montserrat, Arial, sans-serif;line-height:1.1;color:#FCD116;text-transform:uppercase` }, esc(a.label)));
    }
    if (a.holds && S.emoji[a.holds]) {                      // prop hangs from the right hand, the hand still visible
      const p = POSES[a.pose] || POSES.stand, rad = Math.PI / 180;
      const ex = 218 - 68 * Math.sin(p[2] * rad), ey = 232 + 68 * Math.cos(p[2] * rad);
      let hx = ex - 80 * Math.sin((p[2] + p[3]) * rad), hy = ey + 80 * Math.cos((p[2] + p[3]) * rad);
      if (a.facing === "left") hx = 300 - hx;
      const size = wPx * 0.42;
      const hold = el("div", { style: `position:absolute;width:${size}px;height:${size}px;left:${hx / 300 * wPx - size / 2}px;` +
        `top:${(hy + 14) / 600 * hPx}px` }, S.emoji[a.holds]);
      box.appendChild(hold);
    }
    layer.appendChild(box);
    return { box, hPx, wPx, headTop: bottom - hPx, cx: a.x * W };
  }

  function animateActor(a, ref, t0, dur, i, mouth) {
    const q = (sel) => ref.box.querySelectorAll(sel);
    // parts differ per character (a grin has no closed mouth, a silhouette no face): skip what isn't there
    const tset = (n, v, at) => { if (n.length) tl.set(n, v, at); };
    const tto = (n, v, at) => { if (n.length) tl.to(n, v, at); };
    const tfrom = (n, v, at) => { if (n.length) tl.from(n, v, at); };
    const r = rng((a.seed || 1) * 131 + i);
    const pose = POSES[a.pose] || POSES.stand;
    const rot = (sel, deg) => tset(q(sel), { attr: { transform: `rotate(${deg})` } }, t0);
    rot(".p-armL", pose[0]); rot(".p-foreL", pose[1]); rot(".p-armR", pose[2]); rot(".p-foreR", pose[3]);
    const from = { pop: { scale: 0.2, opacity: 0 }, slide_left: { x: -W * 0.6 }, slide_right: { x: W * 0.6 },
                   drop: { y: -H * 0.6 }, fade: { opacity: 0 } }[a.enter];
    if (from) tl.from(ref.box, Object.assign({ duration: 0.45, ease: a.enter === "drop" ? "bounce.out" : "back.out(1.6)",
      transformOrigin: "50% 100%" }, from), t0 + 0.02 * i);
    // breathing + head bob: never a frozen figure
    const breath = 2.2 + r() * 0.8;
    for (let t = 0; t < dur; t += breath) {
      tto(q(".p-body"), { attr: { transform: "translate(0 420) scale(1 1.018) translate(0 -420)" }, duration: breath / 2, ease: "sine.inOut" }, t0 + t);
      tto(q(".p-body"), { attr: { transform: "translate(0 420) scale(1 1) translate(0 -420)" }, duration: breath / 2, ease: "sine.inOut" }, t0 + t + breath / 2);
    }
    // blinks
    for (let t = 0.6 + r() * 1.5; t < dur - 0.2; t += 2.6 + r() * 1.6) {
      tto(q(".p-eyes"), { attr: { transform: "translate(0 178) scale(1 0.08) translate(0 -178)" }, duration: 0.06 }, t0 + t);
      tto(q(".p-eyes"), { attr: { transform: "translate(0 178) scale(1 1) translate(0 -178)" }, duration: 0.08 }, t0 + t + 0.1);
    }
    // gestures
    if (a.pose === "wave") {
      for (let t = 0.3; t < Math.min(dur, 3.2); t += 0.5) {
        tto(q(".p-foreR"), { attr: { transform: "rotate(-5)" }, duration: 0.25, ease: "sine.inOut" }, t0 + t);
        tto(q(".p-foreR"), { attr: { transform: "rotate(-40)" }, duration: 0.25, ease: "sine.inOut" }, t0 + t + 0.25);
      }
    } else if (a.pose === "point" || a.pose === "cheer" || a.pose === "arms_up" || a.pose === "shrug") {
      // raise from the resting arm into the pose (explicit end values: a from() would land on the pre-pose angle)
      const lift = (sel, rest, end, at) => { const n = q(sel); if (n.length) tl.fromTo(n,
        { attr: { transform: `rotate(${rest})` } },
        { attr: { transform: `rotate(${end})` }, duration: 0.35, ease: "back.out(2)", immediateRender: false }, at); };
      if (a.pose !== "point") { lift(".p-armL", 8, pose[0], t0 + 0.15); lift(".p-foreL", 0, pose[1], t0 + 0.15); }
      lift(".p-armR", -8, pose[2], t0 + 0.15); lift(".p-foreR", 0, pose[3], t0 + 0.15);
    } else if (a.pose === "walk") {
      for (let t = 0; t < dur; t += 0.5) {
        tto(q(".p-legL"), { attr: { transform: "rotate(18)" }, duration: 0.25, ease: "sine.inOut" }, t0 + t);
        tto(q(".p-legR"), { attr: { transform: "rotate(-18)" }, duration: 0.25, ease: "sine.inOut" }, t0 + t);
        tto(q(".p-legL"), { attr: { transform: "rotate(-18)" }, duration: 0.25, ease: "sine.inOut" }, t0 + t + 0.25);
        tto(q(".p-legR"), { attr: { transform: "rotate(18)" }, duration: 0.25, ease: "sine.inOut" }, t0 + t + 0.25);
      }
      tl.to(ref.box, { x: (a.facing === "left" ? -1 : 1) * W * 0.18, duration: dur, ease: "none" }, t0);
    }
    // lip-flap on the narration's word timings + a nod on every few words
    if (a.speaking && mouth && mouth.length && ref.box.querySelector(".p-mouth-open")) {
      mouth.forEach(([w0, w1], k) => {
        if (w0 >= dur) return;
        tset(q(".p-mouth-open"), { opacity: 1 }, t0 + w0);
        tset(q(".p-mouth-closed"), { opacity: 0 }, t0 + w0);
        tset(q(".p-mouth-open"), { opacity: 0 }, t0 + Math.min(w1, dur) - 0.02);
        tset(q(".p-mouth-closed"), { opacity: 1 }, t0 + Math.min(w1, dur) - 0.02);
        if (k % 4 === 0) {
          tto(q(".p-head"), { attr: { transform: "rotate(3)" }, duration: 0.18, ease: "sine.out" }, t0 + w0);
          tto(q(".p-head"), { attr: { transform: "rotate(0)" }, duration: 0.25, ease: "sine.in" }, t0 + w0 + 0.18);
        }
      });
    }
  }

  // ------------------------------------------------------------------ props
  function placeProp(p, layer, t0, dur) {
    const svg = S.emoji[p.emoji];
    if (!svg) return;
    const size = p.size * Math.min(W, H);
    const n = p.motion === "rain" ? Math.max(3, Math.min(12, p.count || 6)) : Math.max(1, Math.min(8, p.count || 1));
    const r = rng(p.emoji.length * 97 + Math.round(p.x * 1000));
    for (let k = 0; k < n; k++) {
      const x = (p.motion === "rain" ? (0.08 + 0.84 * r()) * W : p.x * W + (k - (n - 1) / 2) * size * 0.55) - size / 2;
      const y = p.motion === "rain" ? -size : p.y * H - size / 2 - k * size * 0.12;
      const box = el("div", { class: "prop", style: `position:absolute;left:${x}px;top:${y}px;width:${size}px;height:${size}px;z-index:4` }, svg);
      layer.appendChild(box);
      let at = t0 + Math.min(dur * 0.5, Math.max(0, (p.at || 0) * dur)) + k * 0.08;
      if (S.hookUntil && at < S.hookUntil && p.motion !== "rain" && p.y > 0.04 && p.y < 0.34) at = S.hookUntil + 0.1 + k * 0.08;
      if (p.motion === "rain") {
        tl.set(box, { opacity: 0 }, t0);
        tl.to(box, { opacity: 1, duration: 0.01 }, at + k * 0.15);
        tl.to(box, { y: H + size, rotation: (r() - 0.5) * 120, duration: 1.6 + r(), ease: "power1.in" }, at + k * 0.15);
        continue;
      }
      const from = { pop: { scale: 0, opacity: 0 }, slide_left: { x: -W }, slide_right: { x: W }, drop: { y: -H },
                     fade: { opacity: 0 } }[p.enter];
      if (from) {
        tl.set(box, Object.assign({}, from), t0);
        tl.to(box, { scale: 1, opacity: 1, x: 0, y: 0, duration: 0.45, ease: p.enter === "drop" ? "bounce.out" : "back.out(1.8)" }, at);
      }
      const settle = at + 0.45;
      if (p.motion === "float") tl.to(box, { y: -size * 0.08, duration: 1.2, yoyo: true, repeat: Math.max(0, Math.floor((dur - (settle - t0)) / 1.2) - 1), ease: "sine.inOut" }, settle);
      if (p.motion === "spin") tl.to(box, { rotation: 360, duration: Math.max(1, dur - (settle - t0)), ease: "none" }, settle);
      if (p.motion === "shake") tl.to(box, { x: size * 0.04, duration: 0.06, yoyo: true, repeat: 9, ease: "none" }, settle);
      if (p.motion === "pulse") tl.to(box, { scale: 1.12, duration: 0.4, yoyo: true, repeat: 3, ease: "sine.inOut" }, settle);
    }
  }

  // ------------------------------------------------------------------ speech bubbles
  function placeBubble(b, refs, layer, t0, dur) {
    const ref = refs[b.actor];
    if (!ref || !b.text) return;
    const fs = Math.round(Math.min(W, H) * (VERTICAL ? 0.05 : 0.036));
    const maxW = Math.min(SAFE.x1 - SAFE.x0, W * (VERTICAL ? 0.72 : 0.4));
    const box = el("div", { class: "bubble", style: `position:absolute;max-width:${maxW}px;padding:${fs * 0.55}px ${fs * 0.8}px;` +
      `background:#fff;color:#111;border:${Math.max(3, fs * 0.09)}px solid #111;border-radius:${fs * 0.9}px;` +
      `font:800 ${fs}px Montserrat, Arial, sans-serif;line-height:1.15;text-align:center;z-index:6;visibility:hidden` }, esc(b.text));
    layer.appendChild(box);
    const bw = Math.min(maxW, box.offsetWidth || maxW), bh = box.offsetHeight || fs * 2.5;
    let left = Math.min(Math.max(ref.cx - bw / 2, SAFE.x0), SAFE.x1 - bw);
    let top = Math.max(SAFE.y0, ref.headTop - bh - fs * 1.2);
    box.style.left = `${left}px`; box.style.top = `${top}px`; box.style.visibility = "";   // inherit, so a hidden scene hides it too
    const tail = el("div", { style: `position:absolute;left:${Math.min(Math.max(ref.cx - left - fs * 0.5, fs), bw - 2 * fs)}px;` +
      `bottom:${-fs * 0.9}px;width:0;height:0;border-left:${fs * 0.5}px solid transparent;border-right:${fs * 0.5}px solid transparent;` +
      `border-top:${fs}px solid #111` });
    box.appendChild(tail);
    let at = t0 + Math.min(dur * 0.35, Math.max(0.1, (b.at || 0.1) * dur));
    if (S.hookUntil && at < S.hookUntil + 0.1) at = S.hookUntil + 0.1;   // the on-screen hook owns the top until then
    if (at > t0 + dur - 0.6) { box.remove(); return; }                  // too late to be read: no bubble
    tl.set(box, { scale: 0, opacity: 0, transformOrigin: "50% 100%" }, t0);
    tl.to(box, { scale: 1, opacity: 1, duration: 0.3, ease: "back.out(2)" }, at);
  }

  // ------------------------------------------------------------------ cards (animated infographics)
  const NUM = /\d[\d,]*(?:\.\d+)?/g;
  function countUp(node, text, at, dur) {
    const nums = String(text).match(NUM) || [];
    if (!nums.length) { node.textContent = text; return; }
    const o = { p: 0 };
    const render = () => {
      let i = 0;
      node.textContent = String(text).replace(NUM, (raw) => {
        const v = parseFloat(raw.replace(/,/g, "")) * o.p, dec = raw.includes(".") ? raw.split(".")[1].length : 0;
        i++; let s = v.toFixed(dec);
        if (raw.includes(",")) s = Number(s).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
        return s;
      });
    };
    render();
    tl.to(o, { p: 1, duration: dur, ease: "power2.out", onUpdate: render }, at);
  }

  function card(sc, layer, t0, dur) {
    const c = sc.card || {};
    const area = el("div", { class: "card", style: `position:absolute;left:${SAFE.x0}px;top:${SAFE.y0}px;width:${SAFE.x1 - SAFE.x0}px;` +
      `height:${SAFE.y1 - SAFE.y0}px;display:flex;flex-direction:column;justify-content:center;z-index:5;color:#fff;` +
      `font-family:Montserrat, Arial, sans-serif` });
    layer.appendChild(area);
    const fsTitle = Math.round(Math.min(W, H) * (VERTICAL ? 0.07 : 0.06));
    const fsBody = Math.round(Math.min(W, H) * (VERTICAL ? 0.048 : 0.04));
    const title = (txt, color) => el("div", { style: `font:400 ${fsTitle}px Anton, Impact, sans-serif;color:${color || "#FCD116"};` +
      `text-transform:uppercase;line-height:1.05;text-shadow:0 4px 0 rgba(0,0,0,.5);margin-bottom:${fsBody * 0.6}px` }, esc(txt));
    const type = c.type || "stat";
    if (type === "stat") {
      const big = (c.lines && c.lines[0]) || c.title, label = c.lines && c.lines.length ? c.title : "";
      area.style.alignItems = "center"; area.style.textAlign = "center";
      const fig = el("div", { style: `font:400 ${Math.round(fsTitle * 2.4)}px Anton, Impact, sans-serif;color:#FCD116;line-height:1;text-shadow:0 6px 0 rgba(0,0,0,.45)` });
      area.appendChild(fig); countUp(fig, big, t0 + 0.1, Math.min(1.4, dur * 0.5));
      tl.from(fig, { scale: 0.4, opacity: 0, duration: 0.45, ease: "back.out(1.8)" }, t0);
      const bar = el("div", { style: `height:${fsBody * 0.25}px;width:60%;background:#CE1126;margin:${fsBody * 0.5}px auto;transform-origin:50% 50%` });
      area.appendChild(bar); tl.from(bar, { scaleX: 0, duration: 0.5, ease: "power2.out" }, t0 + 0.5);
      if (label) { const l = el("div", { style: `font-weight:800;font-size:${fsBody * 1.25}px` }, esc(label)); area.appendChild(l);
        tl.from(l, { y: fsBody, opacity: 0, duration: 0.4 }, t0 + 0.6); }
      (c.lines || []).slice(1, 3).forEach((x, k) => { const f = el("div", { style: `color:#FCD116;font-weight:800;font-size:${fsBody * 0.8}px;margin-top:${fsBody * 0.3}px` }, esc(x));
        area.appendChild(f); tl.from(f, { opacity: 0, duration: 0.3 }, t0 + 0.9 + k * 0.15); });
    } else if (type === "bars") {
      area.appendChild(title(c.title));
      const rows = (c.lines || []).slice(0, 5).map((line) => { const i = line.lastIndexOf(":"); const label = i > 0 ? line.slice(0, i) : line;
        const raw = i > 0 ? line.slice(i + 1).trim() : line; const m = raw.match(NUM); return { label, raw, v: m ? parseFloat(m[0].replace(/,/g, "")) : 0 }; });
      const top = Math.max(1, ...rows.map((x) => x.v));
      const colors = ["#FCD116", "#CE1126", "#5B8CFF", "#FFFFFF", "#6EE7B7"];
      rows.forEach((row, k) => {
        const wrap = el("div", { style: `margin:${fsBody * 0.35}px 0` });
        wrap.appendChild(el("div", { style: `font-weight:800;font-size:${fsBody}px;margin-bottom:${fsBody * 0.2}px` }, esc(row.label)));
        const line = el("div", { style: "display:flex;align-items:center;gap:" + fsBody * 0.4 + "px" });
        const bar = el("div", { style: `height:${fsBody * 1.2}px;width:${Math.max(4, 72 * row.v / top)}%;background:${colors[k % 5]};border-radius:${fsBody * 0.3}px;transform-origin:0 50%` });
        const val = el("div", { style: `font:400 ${fsBody * 1.35}px Anton, Impact, sans-serif` });
        line.appendChild(bar); line.appendChild(val); wrap.appendChild(line); area.appendChild(wrap);
        tl.from(bar, { scaleX: 0, duration: 0.6, ease: "power2.out" }, t0 + 0.2 + k * 0.25);
        countUp(val, row.raw, t0 + 0.2 + k * 0.25, 0.6);
      });
    } else if (type === "timeline") {
      area.appendChild(title(c.title));
      const list = el("div", { style: `position:relative;padding-left:${fsBody * 1.4}px` });
      const spine = el("div", { style: `position:absolute;left:${fsBody * 0.35}px;top:0;bottom:0;width:${Math.max(3, fsBody * 0.12)}px;background:#fff;transform-origin:50% 0` });
      list.appendChild(spine); area.appendChild(list);
      tl.from(spine, { scaleY: 0, duration: Math.min(1.6, dur * 0.6), ease: "power1.inOut" }, t0 + 0.1);
      (c.lines || []).slice(0, 5).forEach((x, k, all) => {
        const item = el("div", { style: `position:relative;font-weight:800;font-size:${fsBody}px;margin:${fsBody * 0.5}px 0` }, esc(x));
        item.appendChild(el("div", { style: `position:absolute;left:${-fsBody * 1.4 + fsBody * 0.1}px;top:${fsBody * 0.2}px;width:${fsBody * 0.7}px;height:${fsBody * 0.7}px;border-radius:50%;background:#CE1126;border:3px solid #FCD116` }));
        list.appendChild(item);
        tl.from(item, { x: W * 0.06, opacity: 0, duration: 0.35, ease: "power2.out" }, t0 + 0.15 + (k + 0.5) * Math.min(1.6, dur * 0.6) / all.length);
      });
    } else if (type === "quote") {
      let quote = c.title, src = c.lines || [];
      if (src.length && src[0].split(/\s+/).length > Math.max(8, quote.split(/\s+/).length * 2)) { quote = src[0]; src = [c.title, ...src.slice(1)]; }
      const q = el("div", { style: `font-weight:800;font-size:${fsBody * 1.25}px;line-height:1.25` });
      const words = String(quote).replace(/^["“]|["”]$/g, "").split(/\s+/);
      q.innerHTML = "“" + words.map((w) => `<span class="w">${esc(w)} </span>`).join("") + "”";
      area.appendChild(q);
      tl.from(q.querySelectorAll(".w"), { opacity: 0, duration: 0.01, stagger: Math.min(0.12, (dur * 0.55) / words.length) }, t0 + 0.1);
      const s = el("div", { style: `color:#FCD116;font-weight:800;font-size:${fsBody * 0.75}px;margin-top:${fsBody * 0.6}px` }, esc("— " + src.join(" · ")));
      area.appendChild(s); tl.from(s, { opacity: 0, duration: 0.3 }, t0 + dur * 0.6);
    } else if (type === "document") {
      const sheet = el("div", { style: `background:#F2EAD6;color:#111;border-radius:${fsBody * 0.2}px;padding:${fsBody}px;padding-bottom:${fsBody + fsTitle * 1.3}px;box-shadow:0 ${fsBody * 0.3}px 0 rgba(0,0,0,.35);position:relative` });
      sheet.appendChild(el("div", { style: `font:400 ${fsTitle * 0.8}px Anton, Impact, sans-serif;margin-bottom:${fsBody * 0.5}px` }, esc(c.title)));
      (c.lines || []).slice(0, 4).forEach((x, k) => {
        const line = el("div", { style: `position:relative;font-weight:800;font-size:${fsBody * 0.9}px;margin:${fsBody * 0.35}px 0;padding:0 ${fsBody * 0.2}px` });
        if (k === 0) { const hl = el("div", { style: "position:absolute;inset:0;background:#FCD116;transform-origin:0 50%;z-index:0" }); line.appendChild(hl);
          tl.from(hl, { scaleX: 0, duration: 0.5, ease: "power2.out" }, t0 + dur * 0.3); }
        const tx = el("span", { style: "position:relative;z-index:1" }, esc(x)); line.appendChild(tx); sheet.appendChild(line);
      });
      // the stamp gets its own strip under the text (never over a line); written text is English
      const stamp = el("div", { style: `position:absolute;right:${fsBody}px;bottom:${fsBody * 0.6}px;transform:rotate(-8deg);color:#CE1126;` +
        `border:${Math.max(3, fsBody * 0.12)}px solid #CE1126;padding:0 ${fsBody * 0.4}px;font:400 ${fsTitle * 0.75}px Anton, Impact, sans-serif` }, "RECEIPTS");
      sheet.appendChild(stamp); area.appendChild(sheet);
      tl.from(sheet, { y: H * 0.3, opacity: 0, duration: 0.45, ease: "power3.out" }, t0);
      tl.from(stamp, { scale: 2.4, opacity: 0, duration: 0.18, ease: "power4.in" }, t0 + dur * 0.62);
    } else if (type === "map" && c.map) {
      mapCard(c, layer, t0, dur, fsTitle, fsBody);
      area.remove();
    }
  }

  function mapCard(c, layer, t0, dur, fsTitle, fsBody) {
    const m = c.map;                                              // pre-projected by Python (tfs.media.vector)
    const wrap = el("div", { style: `position:absolute;inset:0;background:#10223E;z-index:5` });
    const svg = `<svg class="map" viewBox="${m.start.join(" ")}" preserveAspectRatio="xMidYMid slice" width="${W}" height="${H}">` +
      m.land.map((d) => `<path d="${d}" fill="#34405A" stroke="#46546E" stroke-width="${m.stroke}"/>`).join("") +
      m.ph.map((d) => `<path d="${d}" fill="#DED4BA" stroke="#9A8A70" stroke-width="${m.stroke * 0.6}"/>`).join("") +
      m.hl.map((d) => `<path class="hl" d="${d}" fill="#CE1126" stroke="#FCD116" stroke-width="${m.stroke * 2}" opacity="0"/>`).join("") +
      (m.route ? `<path class="route" d="${m.route}" fill="none" stroke="#FCD116" stroke-width="${m.stroke * 3}" stroke-dasharray="${m.stroke * 8} ${m.stroke * 6}"/>` : "") +
      m.pins.map((p) => `<g class="pin" transform="translate(${p.x} ${p.y})"><circle r="${m.stroke * 7}" fill="#CE1126" stroke="#fff" stroke-width="${m.stroke * 2}"/>` +
        `<g transform="translate(${m.stroke * 12} ${-m.stroke * 4})"><rect x="0" y="${-m.stroke * 10}" rx="${m.stroke * 3}" height="${m.stroke * 20}" width="${m.stroke * (p.label.length * 9 + 12)}" fill="#0E1018" stroke="#FCD116" stroke-width="${m.stroke}"/>` +
        `<text x="${m.stroke * 6}" y="${m.stroke * 5}" font-family="Anton, Impact, sans-serif" font-size="${m.stroke * 14}" fill="#fff">${esc(p.label.toUpperCase())}</text></g></g>`).join("") +
      `</svg>`;
    wrap.innerHTML = svg;
    const head = el("div", { style: `position:absolute;left:0;right:0;top:${VERTICAL ? SAFE.y0 : 0}px;padding:${fsBody * 0.8}px ${SAFE.x0}px;background:rgba(10,14,24,.92);` +
      `font:400 ${fsTitle}px Anton, Impact, sans-serif;color:#FCD116;text-transform:uppercase;text-align:center` }, esc(c.title));
    wrap.appendChild(head);
    layer.appendChild(wrap);
    const svgEl = wrap.querySelector("svg.map");
    tl.to(svgEl, { attr: { viewBox: m.end.join(" ") }, duration: Math.min(1.8, dur * 0.45), ease: "power2.inOut" }, t0 + 0.1);
    tl.to(wrap.querySelectorAll(".hl"), { opacity: 1, duration: 0.5 }, t0 + Math.min(1.8, dur * 0.45));
    const route = wrap.querySelector(".route");
    if (route) { const len = m.routeLength || 3000; tl.fromTo(route, { attr: { "stroke-dashoffset": len } }, { attr: { "stroke-dashoffset": 0 }, duration: 1.2, ease: "power1.inOut" }, t0 + dur * 0.4); }
    wrap.querySelectorAll(".pin").forEach((p, k) => { tl.from(p, { opacity: 0, duration: 0.01 }, t0 + dur * 0.5 + k * 0.12); });
  }

  // ------------------------------------------------------------------ camera
  function camera(inner, move, t0, dur) {
    // pans and shakes stay zoomed in (1.1 covers a 4% slide each way), so the edge of the set never shows
    const to = { push_in: { scale: 1.08 }, pull_out: { scale: 1 }, pan_left: { x: -W * 0.04, scale: 1.1 }, pan_right: { x: W * 0.04, scale: 1.1 },
                 shake: { scale: 1.05 }, static: { scale: 1.02 } }[move] || { scale: 1.03 };
    const from = { pull_out: { scale: 1.08 }, pan_left: { scale: 1.1 }, pan_right: { scale: 1.1 }, shake: { scale: 1.05 } }[move] || {};
    tl.set(inner, Object.assign({ scale: 1, x: 0 }, from), t0);
    tl.to(inner, Object.assign({ duration: dur, ease: "sine.inOut" }, to), t0);
    if (move === "shake") for (let t = 0; t < 0.5; t += 0.05) tl.to(inner, { x: (t * 100 % 2 ? 1 : -1) * W * 0.008, duration: 0.05 }, t0 + t);
  }

  // ------------------------------------------------------------------ build
  S.scenes.forEach((sc, i) => {
    const t0 = sc.start, dur = sc.dur;
    const scene = el("div", { class: "clip scene", "data-start": t0.toFixed(3), "data-duration": dur.toFixed(3), "data-track-index": String(i % 2),
      style: `position:absolute;inset:0;overflow:hidden;${S.look === "doodle" ? "filter:url(#doodle);" : ""}` });
    const inner = el("div", { style: "position:absolute;inset:0;transform-origin:50% 60%" });
    scene.appendChild(inner);
    const bgName = sc.background || "plain";
    const bg = background(bgName).replace(/id="sky"/g, `id="sky${i}"`).replace(/url\(#sky\)/g, `url(#sky${i})`);
    inner.innerHTML = `<svg viewBox="0 0 1000 1000" width="${1000 * SCALE}" height="${1000 * SCALE}" style="${BG_BOX}">${bg}</svg>`;
    stage.appendChild(scene);
    if (sc.kind === "card") {
      inner.querySelector("svg").style.filter = `blur(${Math.round(W * 0.012)}px)`;   // the set, softened, behind the card
      const veil = el("div", { style: "position:absolute;inset:0;background:rgba(10,14,24,.70);z-index:4" });
      inner.appendChild(veil);
      card(sc, inner, t0, dur);
    } else {
      const refs = (sc.actors || []).map((a, k) => placeActor(sc, a, k, inner));
      (sc.actors || []).forEach((a, k) => animateActor(a, refs[k], t0, dur, k, sc.mouth));
      (sc.props || []).forEach((p) => placeProp(p, inner, t0, dur));
      (sc.bubbles || []).forEach((b) => placeBubble(b, refs, inner, t0, dur));
    }
    camera(inner, sc.camera, t0, dur);
    if (i > 0) tl.from(scene, { opacity: 0, duration: 0.18 }, t0);
    // only the live scene (plus the one it cross-fades over) is ever visible
    if (i > 0) tl.set(scene, { visibility: "hidden" }, 0).set(scene, { visibility: "visible" }, t0);
    if (i < S.scenes.length - 1) tl.set(scene, { visibility: "hidden" }, t0 + dur + 0.2);
  });

  window.__timelines = window.__timelines || {};
  window.__timelines[S.id] = tl;
})();
