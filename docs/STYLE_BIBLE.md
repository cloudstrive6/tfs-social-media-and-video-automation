# The Filipino Standard — Style Bible

Every agent loads this file. It describes what we took from **Historically (@HeyHistorically)**
and how it becomes our own voice for Philippine history, politics and culture.

---

## 1. What the reference channel actually does (analysis, Sep 2026)

Source: 23 most recent uploads, 4 full transcripts, 4 thumbnails.

| Metric | Value |
|---|---|
| Subscribers | ~1.4M |
| Avg views / video | ~2–5M (top: *The ENTIRE History of ROME*, 8.6M) |
| Typical length | 11–38 min (avg ~20 min); 3 min outliers |
| Upload rate | ~1 video every 6–10 weeks, hand-animated |
| Audience | 18–34, ~85% male, US/UK/DE/NL |

### 1.1 Script mechanics (the part that makes it addictive)

1. **Cold-open skit (0:00–0:30).** Starts *inside* a scene with character dialogue, not with narration.
   Example: soldiers waking up to fight a war that already ended (*The Shortest War EVER*).
   The viewer is dropped into a funny/absurd moment and has to keep watching to understand it.
2. **"Pop quiz" / wrong-answer hook.** *"What is the most bullied country in history? You might think
   Korea… Congo… Palestine… But no."* Lists plausible answers, knocks each one down, then lands on the
   surprising one. Creates a curiosity gap *and* makes the viewer feel smart.
3. **Contrarian framing.** *"The Jesus Problem"*, *"Fact-Checking Hitler"*, *"Sieging Castles SUCKS actually"*.
   The title promises the video will overturn what you assumed.
4. **Series tag.** *"Historically facts, part 11."* — a ritual that tells returning viewers the "real" video starts now.
5. **Casual, sarcastic narrator voice.** Talks like a friend at a bar who happens to know everything:
   *"very convenient"*, *"Rookie numbers."*, *"this family has zero chill about recycling names"*.
   Modern slang applied to ancient events (Sweden = "the funny country of IKEA and meatballs").
6. **Recurring gags / running characters.** *"Ladies and gentlemen, welcome our recurring guest, Jesus Christ."*
   Counting devices: *"Disappearance number two… reversed."*
7. **Micro-hooks every 30–90 s.** *"Slight problem though…"*, *"Or so he thought."*, *"But of course, it's Poland,
   so the high never lasts."*, *"Let me explain how."* Each one opens a new mini-question before the old one closes.
8. **Fourth-wall breaks.** Narrator coughs mid-sentence, argues with the comment section, addresses the
   viewer directly. Makes it feel live, not produced.
9. **Moral clarity with humor.** Dark topics (slavery, war) are never joked *about* — the joke is aimed at the
   powerful, the hypocritical, or the absurd.
10. **Numbers made visual.** Percentages, dates and counts are shown on screen and repeated out loud.

### 1.2 Visual language

- Hand-drawn **painterly cartoon**, thick dark outlines, soft painted shading, halftone texture, slight
  chromatic aberration.
- Characters are **simple blank-faced figures / country-balls**: white round heads, dot eyes, one strong
  expression. Emotion comes from posture and eyebrows.
- **Cinematic lighting**: dark backgrounds with one warm light source (lantern, fire, window) on the subject.
- Constant **motion**: camera push-ins, parallax layers, shake on impacts, meme inserts.

### 1.3 Thumbnails

- **No text** (at most a date or number drawn *into* the scene, e.g. dates on tombstones).
- **One frozen story moment** that raises a question: a country-ball rising from a grave marked 1025/1480/1939;
  a pocket watch in blood (shortest war); a pirate shaking hands with an officer while a ship burns.
- Irony or contradiction in one frame (a handshake + an explosion).
- 1–2 characters max, big and close, faces readable at phone size; high contrast, warm vs. cold palette.

### 1.4 Titles

- Short (3–7 words). ONE word in CAPS for emphasis: *The ENTIRE History of ROME*, *The Longest War EVER*.
- Superlatives: shortest, longest, dumbest, most hated, most bullied.
- Trailing ellipsis for a smirk: *Sieging Castles SUCKS actually...*, *That Time PIRATES started a COUNTRY...*
- "Problem" / "Fact-checking" framing for contrarian angles.
- Title + thumbnail **never say the same thing** — the thumbnail shows a moment, the title names the mystery.

---

## 2. The Filipino Standard adaptation

### 2.1 Positioning
**"Ang kasaysayan at pulitika ng Pilipinas — explained like your smartest, funniest barkada."**
Why the Philippines is the way it is: history → culture → the systems that create today's problems.

### 2.2 Content pillars (and target mix)

| Pillar | Share | Examples |
|---|---|---|
| **Now, explained** (trending politics, corruption, scandals) | 35% | flood-control scandal, budget insertions, dynasties, hearings |
| **Philippine history, retold** | 30% | Manila galleon, Katipunan infighting, Martial Law, EDSA, Commonwealth |
| **Why we're like this** (culture → systemic problems) | 20% | utang na loob & patronage, padrino system, "bahala na", colonial mentality, traffic, OFW economy |
| **Myths & fact-checks** | 15% | "Marcos gold", "Philippines almost became a US state", viral fake history |

### 2.3 Voice
- **Default language: Taglish** (conversational Manila Taglish, roughly the way Filipino tech/finance YouTubers
  speak). English for technical terms, numbers and quotes; Tagalog for emotion, humor and punchlines.
  Configure in `config/channel.yaml` → `language`.
- Narrator persona: **"Kuya Standard"** — calm, witty, slightly exasperated older brother. Never shouts, never
  preachy. Sarcasm aimed at systems and the powerful, **never** at ordinary Filipinos, regions, ethnic groups,
  religions or the poor.
- Signature ritual (our "Historically facts, part N"): **"Standard Issue #N."** said right after the cold open.
- Recurring gags we own (running characters): *Juan* (everyman, always confused), *Tito Trapo* (a generic,
  fictional corrupt politician — never a real person), *the Galleon* (shows up whenever money leaves the country),
  *the Receipt* (appears whenever we cite a source: "May resibo tayo.").

### 2.4 Visual identity (original — do not copy Historically's characters)
- Painterly cartoon, thick outlines, halftone texture — **our own character design**: round-headed figures with a
  small salakot/barong/baro't saya variants, flag-color accents (blue `#0038A8`, red `#CE1126`, sun yellow `#FCD116`).
- Real living people (politicians, officials) are **never** drawn realistically. Use: (a) generic *Tito Trapo*
  caricature, (b) labeled silhouettes, or (c) cropped public-domain / properly licensed news photos with source
  credit. No AI photorealism of real people, ever.
- Documents, budget tables, maps and timelines are rendered as clean motion-graphics cards (programmatic, cheap,
  always legible).

### 2.5 Hard rules (enforced by the Fact-Check & Legal agent)
1. **Naming:** name people only for history or when a FINAL court conviction exists (cite it). Allegations,
   hearings, audits and ongoing cases use **roles only** ("isang senador", "the contractor"), never names.
2. Every factual claim needs ≥2 independent credible sources or 1 primary source (COA report, court decision,
   Senate/House record, Ombudsman filing); otherwise it is cut. Say "alleged" / "ayon sa COA" until a court rules.
3. No doxxing, no private individuals, no content targeting a family member who holds no office.
4. Satire must be *recognisably* satire and aimed at conduct, not at identity.
5. All sources go in the description ("📚 Sources / Resibo").
6. AI voice and AI images are disclosed per platform rules (YouTube "altered or synthetic content" toggle,
   Meta "AI info" label, TikTok AIGC label).
