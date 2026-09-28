/* Illustrated backgrounds, flat vector, drawn in a 1000x1000 box rendered with "slice" so the same art fills
 * 9:16 and 16:9 (the middle band is always visible). Ground line at y=780. Palette: flag blue/red/yellow accents
 * on warm, slightly desaturated sets, like an editorial cartoon. */
(function () {
  const G = 780;
  const sky = (a, b) => `<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="1000" height="1000" fill="url(#sky)"/>`;
  const floor = (c, line) => `<rect y="${G}" width="1000" height="${1000 - G}" fill="${c}"/><rect y="${G}" width="1000" height="6" fill="${line || "rgba(0,0,0,.18)"}"/>`;
  const flag = (x, y, s) => `<g transform="translate(${x} ${y}) scale(${s})"><rect width="120" height="30" fill="#0038A8"/><rect y="30" width="120" height="30" fill="#CE1126"/><polygon points="0,0 52,30 0,60" fill="#fff"/><circle cx="16" cy="30" r="6" fill="#FCD116"/></g>`;
  const windowBlinds = (x, y, w, h) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="#BFD7EA"/>` +
    Array.from({ length: 9 }, (_, i) => `<rect x="${x}" y="${y + i * h / 9}" width="${w}" height="${h / 18}" fill="#E9EEF3"/>`).join("") +
    `<rect x="${x - 8}" y="${y - 8}" width="${w + 16}" height="${h + 16}" fill="none" stroke="#8D7B68" stroke-width="10"/>`;
  const houses = () => {
    const cols = ["#E9C46A", "#F4A261", "#A8DADC", "#E76F51", "#90BE6D", "#CDB4DB"];
    let s = "";
    for (let i = 0; i < 7; i++) {
      const x = -40 + i * 160, h = 170 + (i * 53) % 90, c = cols[i % cols.length];
      s += `<rect x="${x}" y="${G - h}" width="150" height="${h}" fill="${c}"/><polygon points="${x - 10},${G - h} ${x + 75},${G - h - 60} ${x + 160},${G - h}" fill="#7F5539"/>` +
        `<rect x="${x + 25}" y="${G - h + 40}" width="40" height="40" fill="#3D405B" opacity=".8"/><rect x="${x + 90}" y="${G - 90}" width="38" height="90" fill="#5E3A1E"/>`;
    }
    return s;
  };
  const wires = () => Array.from({ length: 5 }, (_, i) => `<path d="M-20 ${250 + i * 18} Q500 ${330 + i * 30} 1020 ${240 + i * 22}" stroke="#222" stroke-width="3" fill="none"/>`).join("") +
    `<rect x="120" y="200" width="16" height="${G - 200}" fill="#5A4A3A"/><rect x="860" y="190" width="16" height="${G - 190}" fill="#5A4A3A"/>`;
  const jeep = (x, y, s) => `<g transform="translate(${x} ${y}) scale(${s})"><rect x="0" y="40" width="330" height="110" rx="18" fill="#D62828"/><rect x="0" y="40" width="330" height="26" fill="#FCBF49"/>` +
    Array.from({ length: 5 }, (_, i) => `<rect x="${60 + i * 52}" y="76" width="40" height="36" rx="6" fill="#BDE0FE"/>`).join("") +
    `<rect x="-40" y="90" width="60" height="60" rx="8" fill="#ADB5BD"/><circle cx="60" cy="152" r="26" fill="#222"/><circle cx="270" cy="152" r="26" fill="#222"/><path d="M40 40 L60 0 L90 40" fill="#EAE2B7"/><circle cx="75" cy="12" r="10" fill="#FCBF49"/></g>`;

  const BG = {
    plain: () => sky("#15223F", "#0E1426") + `<circle cx="500" cy="420" r="420" fill="#1F3A6B" opacity=".45"/>` + floor("#0C1120"),
    spotlight: () => sky("#07090F", "#0E1220") + `<polygon points="420,0 580,0 760,${G} 240,${G}" fill="#FFF3C4" opacity=".14"/>` + floor("#10131C") +
      `<ellipse cx="500" cy="${G + 10}" rx="260" ry="34" fill="#FFF3C4" opacity=".18"/>`,
    office: () => sky("#E8DCC8", "#D9C8AE") + windowBlinds(620, 190, 260, 300) + flag(90, 200, 1.2) +
      `<rect x="80" y="${G - 330}" width="150" height="330" fill="#8D99AE"/>` + [0, 1, 2].map(i => `<rect x="92" y="${G - 316 + i * 108}" width="126" height="96" fill="#7C889C"/><rect x="138" y="${G - 280 + i * 108}" width="34" height="8" fill="#EDF2F4"/>`).join("") +
      floor("#A1866F") + `<rect x="330" y="${G - 170}" width="420" height="30" fill="#6F4E37"/><rect x="350" y="${G - 140}" width="26" height="140" fill="#5B3F2C"/><rect x="704" y="${G - 140}" width="26" height="140" fill="#5B3F2C"/>`,
    senate: () => sky("#3A2C24", "#24190F") + `<circle cx="500" cy="230" r="110" fill="#C9A227"/><circle cx="500" cy="230" r="86" fill="#1F4FBF"/><circle cx="500" cy="230" r="30" fill="#FCD116"/>` +
      [0, 1, 2].map(i => `<path d="M${40 - i * 40} ${520 + i * 90} Q500 ${440 + i * 90} ${960 + i * 40} ${520 + i * 90} L${980 + i * 40} ${580 + i * 90} Q500 ${500 + i * 90} ${20 - i * 40} ${580 + i * 90}Z" fill="${["#7F4F24", "#6F4518", "#603808"][i]}"/>`).join("") +
      flag(140, 170, 1) + flag(740, 170, 1) + floor("#4A2F1A"),
    courtroom: () => sky("#5C4033", "#3E2A1F") + `<rect x="250" y="360" width="500" height="220" fill="#7F5539"/><rect x="230" y="340" width="540" height="30" fill="#9C6644"/>` +
      `<circle cx="500" cy="230" r="80" fill="#D4A373"/><path d="M460 230 L540 230 M500 190 L500 270" stroke="#7F5539" stroke-width="10"/>` +
      Array.from({ length: 6 }, (_, i) => `<rect x="${i * 180}" y="80" width="14" height="700" fill="#6B4226" opacity=".5"/>`).join("") + floor("#6B4F3A"),
    street: () => sky("#9AD1F5", "#DFF3FF") + `<circle cx="820" cy="140" r="60" fill="#FFE066"/>` + houses() + wires() + floor("#8D8D8D") +
      `<rect y="${G + 90}" width="1000" height="10" fill="#EDEDED" stroke-dasharray="60 40" stroke="#EDEDED"/>` + jeep(560, G + 20, 0.9),
    barangay_hall: () => sky("#9AD1F5", "#E7F6FF") + `<rect x="200" y="330" width="600" height="${G - 330}" fill="#F1FAEE"/><polygon points="170,330 500,190 830,330" fill="#E63946"/>` +
      `<rect x="330" y="360" width="340" height="60" fill="#1D3557"/><rect x="440" y="${G - 170}" width="120" height="170" fill="#8D5524"/>` +
      `<rect x="880" y="220" width="10" height="${G - 220}" fill="#999"/>` + flag(890, 220, 0.9) + floor("#B5A48B"),
    province: () => sky("#8EC5FC", "#E0F4FF") + `<path d="M0 520 L180 330 L330 480 L520 280 L720 470 L860 360 L1000 480 L1000 ${G} L0 ${G}Z" fill="#6A994E"/>` +
      [0, 1, 2, 3].map(i => `<path d="M0 ${600 + i * 45} Q500 ${560 + i * 45} 1000 ${600 + i * 45}" stroke="#A7C957" stroke-width="16" fill="none"/>`).join("") +
      `<g transform="translate(120 ${G - 200})"><rect x="0" y="80" width="200" height="120" fill="#B08968"/><polygon points="-30,90 100,0 230,90" fill="#DDB892"/></g>` +
      [760, 880].map(x => `<rect x="${x}" y="${G - 330}" width="16" height="330" fill="#7F5539"/><path d="M${x + 8} ${G - 330} q-90 20 -130 90 M${x + 8} ${G - 330} q90 20 130 90 M${x + 8} ${G - 330} q-40 -70 -110 -60 M${x + 8} ${G - 330} q40 -70 110 -60" stroke="#386641" stroke-width="22" fill="none" stroke-linecap="round"/>`).join("") + floor("#6A994E"),
    city_night: () => sky("#0B132B", "#1C2541") + Array.from({ length: 40 }, (_, i) => `<circle cx="${(i * 97) % 1000}" cy="${(i * 53) % 300}" r="2" fill="#fff" opacity=".7"/>`).join("") +
      Array.from({ length: 11 }, (_, i) => { const x = i * 95 - 20, h = 250 + (i * 131) % 330; return `<rect x="${x}" y="${G - h}" width="88" height="${h}" fill="${["#1B263B", "#27324A", "#3A506B"][i % 3]}"/>` +
        Array.from({ length: Math.floor(h / 45) }, (_, j) => `<rect x="${x + 14 + (j % 2) * 34}" y="${G - h + 18 + j * 42}" width="20" height="16" fill="#FFD166" opacity="${(i + j) % 3 ? .9 : .25}"/>`).join(""); }).join("") + floor("#0B0F1E"),
    flood: () => sky("#6C7A89", "#AAB7C4") + houses() + wires() + `<rect y="${G - 150}" width="1000" height="${1000 - G + 150}" fill="#5B7C99" opacity=".92"/>` +
      Array.from({ length: 6 }, (_, i) => `<path d="M${-40 + i * 180} ${G - 130 + (i % 2) * 40} q45 -26 90 0 t90 0" stroke="#D6E6F2" stroke-width="6" fill="none"/>`).join(""),
    newsroom: () => sky("#101828", "#1D2939") + `<rect x="120" y="150" width="760" height="420" rx="16" fill="#0B1220" stroke="#344054" stroke-width="10"/>` +
      `<rect x="150" y="180" width="700" height="360" fill="#1F4FBF" opacity=".35"/>` + `<rect x="0" y="${G - 150}" width="1000" height="150" fill="#344054"/><rect x="0" y="${G - 150}" width="1000" height="18" fill="#CE1126"/>` + floor("#1D2939"),
    kitchen: () => sky("#FFE8D6", "#FFD7BA") + windowBlinds(90, 180, 230, 240) + `<rect x="520" y="200" width="380" height="140" fill="#CB997E"/><rect x="520" y="${G - 220}" width="440" height="220" fill="#B08968"/>` +
      `<rect x="560" y="${G - 280}" width="90" height="70" rx="20" fill="#E5E5E5"/><rect x="590" y="${G - 296}" width="30" height="20" rx="6" fill="#999"/>` + floor("#DDBEA9"),
    airport: () => sky("#CAF0F8", "#ADE8F4") + `<rect x="0" y="120" width="1000" height="400" fill="#90E0EF" opacity=".5"/>` + Array.from({ length: 6 }, (_, i) => `<rect x="${i * 170}" y="120" width="12" height="400" fill="#495057"/>`).join("") +
      `<rect x="330" y="560" width="340" height="150" fill="#212529"/>` + Array.from({ length: 4 }, (_, i) => `<rect x="350" y="${580 + i * 32}" width="300" height="20" fill="#FFD60A" opacity=".75"/>`).join("") + floor("#ADB5BD"),
    classroom: () => sky("#FEFAE0", "#F5EBD0") + `<rect x="200" y="170" width="600" height="330" fill="#2D6A4F" stroke="#7F5539" stroke-width="16"/>` + flag(840, 180, .9) +
      [0, 1, 2].map(i => `<rect x="${130 + i * 280}" y="${G - 120}" width="200" height="22" fill="#9C6644"/><rect x="${150 + i * 280}" y="${G - 98}" width="14" height="98" fill="#7F5539"/><rect x="${306 + i * 280}" y="${G - 98}" width="14" height="98" fill="#7F5539"/>`).join("") + floor("#DDB892"),
    history_spanish: () => sky("#E9DCC0", "#D8C39A") + `<rect x="120" y="260" width="320" height="${G - 260}" fill="#C9B38A"/><polygon points="100,260 280,120 460,260" fill="#B69B6B"/><rect x="250" y="160" width="60" height="100" fill="#B69B6B"/>` +
      `<path d="M240 ${G} L240 520 Q280 470 320 520 L320 ${G}" fill="#6F5B3E"/>` + `<rect x="560" y="360" width="340" height="${G - 360}" fill="#D6C29A"/><rect x="560" y="360" width="340" height="120" fill="#8B6B45"/>` +
      Array.from({ length: 5 }, (_, i) => `<rect x="${575 + i * 64}" y="380" width="48" height="80" fill="#EFE3C8"/>`).join("") + floor("#BFA67A"),
  };

  function background(name) { return (BG[name] || BG.plain)(); }
  window.TFS_BACKGROUNDS = { background, names: Object.keys(BG), GROUND: G };
})();
