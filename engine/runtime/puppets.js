/* The Filipino Standard cast as SVG puppets (round-headed, Historically-like, drawn in code).
 * Every puppet is a <g> in a 300x600 box, feet at y=580, with named parts the timeline animates:
 *   .p-body (breathing), .p-head (bob), .p-eyes (blink), .p-brows, .p-mouth-closed / .p-mouth-open (lip-flap),
 *   .p-armL/.p-armR (shoulder) > .p-foreL/.p-foreR (elbow), .p-legL/.p-legR (walk).
 * Arm angles: 0 = hanging down. viewer-right arm: -90 points right, -180 straight up; viewer-left mirrored.
 */
(function () {
  const SKIN = ["#D9A574", "#C98F5E", "#E6BC92", "#B97F52"];
  const CAST = {
    kuya_standard: { skin: "#D9A574", hair: "bald", shirt: "#1F4FBF", cuff: "#FCD116", cuff2: "#CE1126",
      pants: "#23262E", shoes: "#6B4423", label: "Kuya Standard", extra: "barong" },
    juan: { skin: "#C98F5E", hair: "messy", shirt: "#8EC5F2", pants: "#4F6FA8", shoes: "#3A3A3A",
      shorts: true, label: "Juan", extra: "" },
    tito_trapo: { skin: "#E0AE80", hair: "slick", shirt: "#F2E6C9", pants: "#2A2A2A", shoes: "#111111",
      belly: true, sash: "#CE1126", watch: "#E8B923", grin: true, label: "Tito Trapo", extra: "barong" },
    official: { hair: "short", shirt: "#4A5260", pants: "#2B2F36", shoes: "#111", tie: "#8C1C24", jacket: true },
    senator: { hair: "side", shirt: "#2E3440", pants: "#1F232B", shoes: "#111", tie: "#1F4FBF", jacket: true, pin: true },
    judge: { hair: "gray", shirt: "#15161A", pants: "#15161A", shoes: "#111", robe: true },
    police: { hair: "short", shirt: "#2C4A8A", pants: "#1D2E57", shoes: "#111", cap: "#1D2E57", badge: true },
    citizen: { hair: "short", shirt: null, pants: "#4B5563", shoes: "#333" },
    woman: { hair: "long", shirt: null, pants: "#374151", shoes: "#333", skirt: true },
    elder: { hair: "white", shirt: "#9CA3AF", pants: "#4B5563", shoes: "#333", cane: true },
    child: { hair: "messy", shirt: null, pants: "#3B82F6", shoes: "#333", small: true, shorts: true },
    farmer: { hair: "short", shirt: "#E7E1CF", pants: "#6B5B45", shoes: "#6B5B45", salakot: true },
    vendor: { hair: "bun", shirt: null, pants: "#4B5563", shoes: "#333", apron: "#F59E0B", skirt: true },
    ofw: { hair: "short", shirt: null, pants: "#374151", shoes: "#333", backpack: "#DC2626", cap: "#DC2626" },
    student: { hair: "short", shirt: "#F8FAFC", pants: "#1E3A8A", shoes: "#111", tie: "#1E3A8A" },
    nurse: { hair: "bun", shirt: "#E0F2F1", pants: "#E0F2F1", shoes: "#FFFFFF", cross: true },
    worker: { hair: "short", shirt: "#F97316", pants: "#374151", shoes: "#553", hardhat: "#FACC15" },
    silhouette: { silhouette: true },
  };
  const SHIRTS = ["#EF4444", "#10B981", "#F59E0B", "#8B5CF6", "#EC4899", "#14B8A6", "#6366F1", "#84CC16"];

  function rng(seed) { // mulberry32: deterministic variety (HyperFrames renders must be deterministic)
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function hairSvg(kind, color) {
    switch (kind) {
      case "bald": return "";
      case "messy": return `<path d="M58 118 Q60 30 150 32 Q240 30 244 118 Q236 84 214 92 Q206 62 184 80 Q168 52 150 76 Q130 50 116 80 Q96 62 90 92 Q70 82 58 118Z" fill="${color}"/>`;
      case "slick": return `<path d="M56 122 Q58 36 150 34 Q244 36 246 122 Q238 70 150 64 Q84 66 56 122Z" fill="${color}"/><path d="M92 60 Q150 40 214 62" stroke="#ffffff" stroke-opacity=".45" stroke-width="6" fill="none"/>`;
      case "short": return `<path d="M58 120 Q58 38 150 36 Q242 38 242 120 Q232 78 150 74 Q70 78 58 120Z" fill="${color}"/>`;
      case "side": return `<path d="M58 124 Q58 36 150 34 Q244 38 242 116 Q226 70 132 72 Q92 76 58 124Z" fill="${color}"/>`;
      case "gray": return `<path d="M58 122 Q60 40 150 38 Q240 40 242 122 Q228 82 150 78 Q72 82 58 122Z" fill="#9CA3AF"/>`;
      case "white": return `<path d="M60 126 Q62 44 150 42 Q238 44 240 126 Q226 86 150 84 Q74 86 60 126Z" fill="#E5E7EB"/>`;
      case "long": return `<path d="M50 230 Q40 40 150 34 Q260 40 250 230 L232 230 Q236 110 150 78 Q64 110 68 230Z" fill="${color}"/>`;
      case "bun": return `<circle cx="150" cy="30" r="30" fill="${color}"/><path d="M58 122 Q58 40 150 38 Q242 40 242 122 Q230 82 150 78 Q70 82 58 122Z" fill="${color}"/>`;
      default: return "";
    }
  }

  function arm(side, c, shirt) {
    const x = side === "L" ? 82 : 218;
    const sleeve = c.extra === "barong" ? shirt : shirt;
    const cuff = c.cuff ? `<rect x="-13" y="56" width="26" height="12" rx="4" fill="${c.cuff}"/><rect x="-13" y="62" width="26" height="4" fill="${c.cuff2 || c.cuff}"/>` : "";
    const watch = c.watch && side === "R" ? `<rect x="-14" y="54" width="28" height="12" rx="4" fill="${c.watch}"/>` : "";
    return `<g transform="translate(${x} 232)"><g class="p-arm${side}" transform="rotate(0)">` +
      `<rect x="-15" y="-6" width="30" height="80" rx="15" fill="${sleeve}"/>` +
      `<g transform="translate(0 68)"><g class="p-fore${side}" transform="rotate(0)">` +
      `<rect x="-13" y="-6" width="26" height="78" rx="13" fill="${sleeve}"/>${cuff}${watch}` +
      `<circle cx="0" cy="80" r="16" fill="${c.skin}"/></g></g></g></g>`;
  }

  function face(c, expr) {
    const brows = {
      neutral: ["M104 158 L136 158", "M164 158 L196 158"],
      happy: ["M104 154 Q120 146 136 154", "M164 154 Q180 146 196 154"],
      worried: ["M104 160 L136 150", "M164 150 L196 160"],
      sad: ["M104 162 L136 152", "M164 152 L196 162"],
      angry: ["M104 150 L136 162", "M164 162 L196 150"],
      shocked: ["M104 144 Q120 136 136 144", "M164 144 Q180 136 196 144"],
      smug: ["M104 158 L136 156", "M164 150 Q180 140 196 150"],
      confused: ["M104 152 L136 158", "M164 146 Q180 140 196 150"],
    }[expr] || ["M104 158 L136 158", "M164 158 L196 158"];
    const closed = {
      neutral: "M130 212 Q150 222 170 212", happy: "M120 206 Q150 238 180 206",
      worried: "M130 218 Q150 210 170 218", sad: "M126 222 Q150 206 174 222",
      angry: "M128 216 L172 216", shocked: "M140 214 Q150 212 160 214",
      smug: "M132 214 Q158 222 176 206", confused: "M130 216 Q150 210 172 218",
    }[expr] || "M130 212 Q150 222 170 212";
    const grin = c.grin ? `<path d="M112 200 Q150 250 188 200 Q150 222 112 200Z" fill="#fff" stroke="#3a1a1a" stroke-width="4"/>` : "";
    return `<g class="p-brows" stroke="#2a1a14" stroke-width="7" stroke-linecap="round" fill="none"><path d="${brows[0]}"/><path d="${brows[1]}"/></g>` +
      `<g class="p-eyes" transform="translate(0 178) scale(1 1) translate(0 -178)"><circle cx="120" cy="178" r="9" fill="#141414"/><circle cx="180" cy="178" r="9" fill="#141414"/></g>` +
      (grin || `<path class="p-mouth-closed" d="${closed}" stroke="#4a1f1a" stroke-width="7" stroke-linecap="round" fill="none"/>`) +
      `<ellipse class="p-mouth-open" cx="150" cy="214" rx="16" ry="14" fill="#5a1f1a" opacity="0"/>`;
  }

  function body(c, shirt) {
    const belly = c.belly ? `<ellipse cx="150" cy="340" rx="92" ry="86" fill="${shirt}"/>` : "";
    const barong = c.extra === "barong" ? `<path d="M150 232 L150 400" stroke="${c.cuff || "#d8c9a6"}" stroke-width="3" stroke-dasharray="6 6" opacity=".8"/>` +
      `<path d="M112 250 Q150 270 188 250" stroke="#ffffff" stroke-opacity=".35" stroke-width="5" fill="none"/>` : "";
    const jacket = c.jacket ? `<path d="M76 234 L124 234 L150 300 L176 234 L224 234 L224 410 L76 410Z" fill="${shirt}"/><path d="M124 234 L150 300 L176 234Z" fill="#F3F4F6"/>` : "";
    const tie = c.tie ? `<path d="M144 236 L156 236 L162 312 L150 330 L138 312Z" fill="${c.tie}"/>` : "";
    const sash = c.sash ? `<path d="M88 250 L212 380 L200 396 L76 266Z" fill="${c.sash}"/>` : "";
    const robe = c.robe ? `<path d="M70 232 L230 232 L246 520 L54 520Z" fill="#15161A"/><path d="M130 232 L150 262 L170 232" fill="#F9FAFB"/>` : "";
    const apron = c.apron ? `<rect x="104" y="300" width="92" height="120" rx="10" fill="${c.apron}"/>` : "";
    const cross = c.cross ? `<rect x="164" y="262" width="26" height="8" fill="#DC2626"/><rect x="173" y="253" width="8" height="26" fill="#DC2626"/>` : "";
    const badge = c.badge ? `<polygon points="182,262 192,272 182,284 172,272" fill="#E8B923"/>` : "";
    const pin = c.pin ? `<circle cx="184" cy="266" r="6" fill="#E8B923"/>` : "";
    const backpack = c.backpack ? `<rect x="56" y="244" width="40" height="120" rx="14" fill="${c.backpack}"/>` : "";
    return backpack + `<rect x="76" y="224" width="148" height="196" rx="46" fill="${shirt}"/>` + belly + jacket + tie + barong + sash + apron + cross + badge + pin + robe;
  }

  function legs(c) {
    const pants = c.pants, shoe = c.shoes;
    const lower = c.shorts ? c.skin : pants;
    const skirt = c.skirt ? `<path d="M80 400 L220 400 L236 478 L64 478Z" fill="${pants}"/>` : "";
    const leg = (side, x) => `<g transform="translate(${x} 410)"><g class="p-leg${side}" transform="rotate(0)">` +
      `<rect x="-19" y="0" width="38" height="${c.shorts ? 64 : 150}" rx="14" fill="${pants}"/>` +
      (c.shorts ? `<rect x="-15" y="56" width="30" height="96" rx="14" fill="${lower}"/>` : "") +
      `<ellipse cx="${side === "L" ? -8 : 8}" cy="160" rx="30" ry="14" fill="${shoe}"/></g></g>`;
    return leg("L", 118) + leg("R", 182) + skirt;
  }

  function hats(c) {
    let s = "";
    if (c.salakot) s += `<path d="M20 112 Q150 -20 280 112 Z" fill="#C8A165" stroke="#8B6B3E" stroke-width="5"/>`;
    if (c.cap) s += `<path d="M62 100 Q150 14 238 100 Z" fill="${c.cap}"/><rect x="150" y="90" width="110" height="16" rx="8" fill="${c.cap}"/>`;
    if (c.hardhat) s += `<path d="M58 106 Q150 6 242 106 Z" fill="${c.hardhat}"/><rect x="46" y="98" width="208" height="16" rx="8" fill="${c.hardhat}"/>`;
    return s;
  }

  /** Build one puppet. opts: {who, expression, seed, label} -> SVG <g> markup (300x600 box). */
  function puppet(opts) {
    const r = rng(opts.seed || 1);
    const base = CAST[opts.who] || CAST.citizen;
    if (base.silhouette) {
      return `<g class="puppet"><g class="p-body"><rect x="76" y="224" width="148" height="196" rx="46" fill="#2B2F3A"/>` +
        `<rect x="99" y="410" width="38" height="150" rx="14" fill="#2B2F3A"/><rect x="163" y="410" width="38" height="150" rx="14" fill="#2B2F3A"/></g>` +
        `<g class="p-head" transform="rotate(0)"><circle cx="150" cy="130" r="95" fill="#2B2F3A"/></g>` +
        `<g transform="translate(82 232)"><g class="p-armL" transform="rotate(0)"><rect x="-15" y="-6" width="30" height="150" rx="15" fill="#2B2F3A"/><g class="p-foreL" transform="rotate(0)"></g></g></g>` +
        `<g transform="translate(218 232)"><g class="p-armR" transform="rotate(0)"><rect x="-15" y="-6" width="30" height="150" rx="15" fill="#2B2F3A"/><g class="p-foreR" transform="rotate(0)"></g></g></g>` +
        (opts.label ? `<text x="150" y="140" text-anchor="middle" font-family="Montserrat" font-weight="800" font-size="30" fill="#FCD116">${opts.label}</text>` : "") +
        `<g class="p-eyes" transform="translate(0 0) scale(1 1) translate(0 0)"></g><g class="p-brows"></g></g>`;
    }
    const c = Object.assign({}, base);
    c.skin = c.skin || SKIN[Math.floor(r() * SKIN.length)];
    const shirt = c.shirt || SHIRTS[Math.floor(r() * SHIRTS.length)];
    const hairColor = ["#1B1B1B", "#2C1E14", "#3B2A1E"][Math.floor(r() * 3)];
    const expr = opts.expression || "neutral";
    return `<g class="puppet">` +
      `<g class="p-legs">${legs(c)}</g>` +
      `<g class="p-body" transform="translate(0 420) scale(1 1) translate(0 -420)">${body(c, shirt)}</g>` +
      arm("L", c, shirt) +
      `<g transform="translate(150 226)"><g class="p-head" transform="rotate(0)"><g transform="translate(-150 -226)"><rect x="130" y="196" width="40" height="40" fill="${c.skin}"/>` +
      `<circle cx="150" cy="130" r="95" fill="${c.skin}"/>` +
      `<circle cx="56" cy="140" r="14" fill="${c.skin}"/><circle cx="244" cy="140" r="14" fill="${c.skin}"/>` +
      hairSvg(c.hair, hairColor) + face(c, expr) + hats(c) + `</g></g></g>` +
      arm("R", c, shirt) +
      (c.cane ? `<rect x="252" y="330" width="10" height="250" rx="5" fill="#6B4423"/>` : "") +
      `</g>`;
  }

  // arm poses: [upperL, foreL, upperR, foreR] in degrees
  // Angles (degrees, clockwise from hanging down) for [upperL, foreL, upperR, foreR], derived from the joint
  // positions: shoulders (82|218, 232), upper arm and forearm ~74 units. Viewer-left arm: +90 = out left,
  // +180 = up. Viewer-right arm: -90 = out right, -180 = up. Forearm angles are relative to the upper arm.
  const POSES = {
    stand: [8, 0, -8, 0],
    wave: [8, 0, -150, -30],
    point: [8, 0, -92, 0],
    shrug: [40, 70, -40, -70],            // elbows out, forearms up, palms to the sky
    arms_up: [165, 0, -165, 0],
    think: [8, 0, -20, 156],              // right hand on the chin
    facepalm: [8, 0, -120, -136],           // right hand on the forehead
    hands_on_hips: [45, -66, -45, 66],
    hold: [8, 0, -20, -70],             // forearms forward, holding something
    walk: [18, 0, -18, 0],
    cheer: [150, 20, -150, -20],
    cross_arms: [-10, -80, 10, 80],
  };

  window.TFS_PUPPETS = { puppet, POSES, CAST, rng };
})();
