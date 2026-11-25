/* TFS atlas helpers: pure functions, no DOM, no clocks. Loaded into the page before atlas.js (window.TFSLIB) and
 * required by the unit tests under node (module.exports).
 *
 * - an orthographic globe: rotate lon/lat into view space, clip rings to the visible hemisphere (the cut follows
 *   the horizon circle), great-circle interpolation (slerp) for route arcs, a graticule;
 * - figures for count-ups: "₱19.66 TRILLION" -> prefix, number, decimals, suffix, and back at any value;
 * - small timing helpers (clamped progress, even spread of build steps).
 * Sets window.TFSLIB (globalThis.TFSLIB under node: tests run it with vm.runInThisContext).
 * Written for TFS (2026-11-25); the maths is the textbook orthographic projection, no third-party code.
 */
(function (root) {
  const RAD = Math.PI / 180;

  // ---------------------------------------------------------------- sphere
  function vec(lon, lat) {
    const l = lon * RAD, p = lat * RAD, c = Math.cos(p);
    return [c * Math.cos(l), c * Math.sin(l), Math.sin(p)];
  }

  function toLonLat(v) {
    const n = Math.hypot(v[0], v[1], v[2]) || 1;
    return [Math.atan2(v[1], v[0]) / RAD, Math.asin(Math.max(-1, Math.min(1, v[2] / n))) / RAD];
  }

  /** View-space point for a lon/lat seen from a globe centred on (lam, phi): [depth, right, up]; depth >= 0 is
   * the visible side. */
  function rot(lon, lat, lam, phi) {
    const v = vec(lon - lam, lat), cp = Math.cos(phi * RAD), sp = Math.sin(phi * RAD);
    return [v[0] * cp + v[2] * sp, v[1], -v[0] * sp + v[2] * cp];
  }

  /** Great-circle point at fraction f between two lon/lats (spherical linear interpolation). */
  function slerp(a, b, f) {
    const va = vec(a[0], a[1]), vb = vec(b[0], b[1]);
    const d = Math.acos(Math.max(-1, Math.min(1, va[0] * vb[0] + va[1] * vb[1] + va[2] * vb[2])));
    if (d < 1e-9) return [a[0], a[1]];
    const s = Math.sin(d), ka = Math.sin((1 - f) * d) / s, kb = Math.sin(f * d) / s;
    return toLonLat([ka * va[0] + kb * vb[0], ka * va[1] + kb * vb[1], ka * va[2] + kb * vb[2]]);
  }

  function angle(a, b) {
    const va = vec(a[0], a[1]), vb = vec(b[0], b[1]);
    return Math.acos(Math.max(-1, Math.min(1, va[0] * vb[0] + va[1] * vb[1] + va[2] * vb[2]))) / RAD;
  }

  /** Clip one ring (view-space points) to depth >= 0. Where the ring leaves and re-enters the visible side, the
   * cut runs along the horizon circle (points every 6 degrees), so big countries keep a round edge. */
  function clipRing(pts) {
    const out = [];
    const n = pts.length;
    if (!n) return out;
    const cross = (a, b) => {
      const t = a[0] / (a[0] - b[0]);
      const y = a[1] + (b[1] - a[1]) * t, z = a[2] + (b[2] - a[2]) * t, m = Math.hypot(y, z) || 1;
      return [0, y / m, z / m];
    };
    let exit = null;
    const arcTo = (p) => {                     // walk the horizon from the last exit to this entry, shorter way round
      if (!exit) return;
      let a0 = Math.atan2(exit[2], exit[1]), a1 = Math.atan2(p[2], p[1]);
      let d = a1 - a0;
      while (d > Math.PI) d -= 2 * Math.PI;
      while (d < -Math.PI) d += 2 * Math.PI;
      const k = Math.floor(Math.abs(d) / (6 * RAD));
      for (let i = 1; i <= k; i++) {
        const a = a0 + d * i / (k + 1);
        out.push([0, Math.cos(a), Math.sin(a)]);
      }
      exit = null;
    };
    for (let i = 0; i < n; i++) {
      const a = pts[i], b = pts[(i + 1) % n];
      const ina = a[0] >= 0, inb = b[0] >= 0;
      if (ina && inb) out.push(b);
      else if (ina && !inb) { exit = cross(a, b); out.push(exit); }
      else if (!ina && inb) { const e = cross(a, b); arcTo(e); out.push(e); out.push(b); }
    }
    if (exit && out.length) arcTo(out[0]);
    return out;
  }

  /** SVG path for lon/lat rings on a globe of radius r centred at (cx, cy), viewed from (lam, phi). Rings that
   * are wholly on the far side vanish. `closed` false draws open polylines (graticule, routes). */
  function pathRings(rings, lam, phi, r, cx, cy, closed = true) {
    let d = "";
    for (const ring of rings) {
      const v = ring.map((p) => rot(p[0], p[1], lam, phi));
      if (closed) {
        if (!v.some((p) => p[0] >= 0)) continue;
        const c = clipRing(v);
        if (c.length < 3) continue;
        d += "M" + c.map((p) => `${(cx + r * p[1]).toFixed(1)} ${(cy - r * p[2]).toFixed(1)}`).join("L") + "Z";
      } else {
        let pen = false;
        for (const p of v) {
          if (p[0] < 0) { pen = false; continue; }
          d += (pen ? "L" : "M") + `${(cx + r * p[1]).toFixed(1)} ${(cy - r * p[2]).toFixed(1)}`;
          pen = true;
        }
      }
    }
    return d;
  }

  /** Screen point for a lon/lat, lifted `h` (fraction of r) off the surface; `vis` false when it is hidden
   * behind the globe. */
  function point(lon, lat, lam, phi, r, cx, cy, h = 0) {
    const p = rot(lon, lat, lam, phi), k = r * (1 + h);
    const x = cx + k * p[1], y = cy - k * p[2];
    const vis = p[0] >= 0 || Math.hypot(k * p[1], k * p[2]) > r;
    return { x, y, vis, depth: p[0] };
  }

  /** Route arc from a to b drawn up to fraction f (0..1), lifted into an arch that peaks at mid-route. */
  function arcPath(a, b, f, lam, phi, r, cx, cy) {
    const span = angle(a, b);
    const lift = Math.min(0.22, 0.04 + span / 400);
    const steps = Math.max(8, Math.ceil(48 * f));
    let d = "", pen = false;
    for (let i = 0; i <= steps; i++) {
      const u = f * i / steps;
      const ll = slerp(a, b, u);
      const p = point(ll[0], ll[1], lam, phi, r, cx, cy, lift * Math.sin(Math.PI * u));
      if (!p.vis) { pen = false; continue; }
      d += (pen ? "L" : "M") + `${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
      pen = true;
    }
    return d;
  }

  function graticule(step = 20) {
    const lines = [];
    for (let lon = -180; lon < 180; lon += step) {
      const l = [];
      for (let lat = -80; lat <= 80; lat += 4) l.push([lon, lat]);
      lines.push(l);
    }
    for (let lat = -60; lat <= 60; lat += step) {
      const l = [];
      for (let lon = -180; lon <= 180; lon += 4) l.push([lon, lat]);
      lines.push(l);
    }
    return lines;
  }

  // ---------------------------------------------------------------- figures for count-ups
  /** "₱19.66 TRILLION" -> {pre:"₱", num:19.66, dec:2, suf:" TRILLION", comma:false}; null when there is no
   * number. Commas in the number ("170,598") are kept when counting. */
  function parseFig(text) {
    const m = String(text ?? "").match(/^(.*?)(\d[\d,]*(?:\.\d+)?)(.*)$/s);
    if (!m) return null;
    const raw = m[2];
    const comma = raw.includes(",");
    const clean = raw.replace(/,/g, "");
    const dec = clean.includes(".") ? clean.split(".")[1].length : 0;
    return { pre: m[1], num: parseFloat(clean), dec, suf: m[3], comma };
  }

  function fmtFig(f, v) {
    if (!f) return "";
    let s = Math.max(0, v).toFixed(f.dec);
    if (f.comma) {
      const [i, d] = s.split(".");
      s = i.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (d ? "." + d : "");
    }
    return f.pre + s + f.suf;
  }

  /** The figure as shown at count-up progress u (0..1): the final text exactly at u >= 1. */
  function figAt(text, u) {
    const f = parseFig(text);
    if (!f) return String(text ?? "");
    if (u >= 1) return String(text);
    return fmtFig(f, f.num * Math.max(0, u));
  }

  // ---------------------------------------------------------------- timing
  function prog(t, t0, dur) { return dur <= 0 ? (t >= t0 ? 1 : 0) : Math.max(0, Math.min(1, (t - t0) / dur)); }

  /** Start times for n build steps: the step's own `at` when given and inside the shot, else spread evenly
   * after `lead` seconds with at least `minGap` between them. */
  function stepTimes(items, t0, t1, lead = 0.5, minGap = 0.9) {
    const n = items.length;
    const gap = Math.max(minGap, (t1 - t0 - lead - 1.0) / Math.max(1, n));
    return items.map((it, i) => {
      const at = it && typeof it.at === "number" ? it.at : null;
      return at !== null && at >= t0 && at < t1 ? at : t0 + lead + i * gap;
    });
  }

  const API = { vec, toLonLat, rot, slerp, angle, clipRing, pathRings, point, arcPath, graticule,
                parseFig, fmtFig, figAt, prog, stepTimes };
  root.TFSLIB = API;
})(typeof window !== "undefined" ? window : globalThis);
