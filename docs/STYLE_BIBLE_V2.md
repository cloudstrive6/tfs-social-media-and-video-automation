# The Filipino Standard: Style Bible v2 (atlas style)

Approved by the owner on 2026-11-24 after the revamp pilot ("Built to Fail" chapter and the "Know Your Government"
Short on how to remove a president). Every writing and review agent loads this file. It is the channel's only
style bible.

## 1. What we make
- **Built to Fail** (long-form, 8 to 15 min): one Philippine system per episode (term limits, impeachment, the
  budget, party-list, dynasties, local government), why it was designed that way, how it fails in practice, how
  another democracy (usually New Zealand) handles the same job, and what would change it.
- **Know Your Government** (Shorts, 35 to 58 s): one rule of how the Philippine government works, explained so a
  viewer can repeat it to a friend.
- **Now, explained** (either format): a current story told through the system that produced it, never through a
  personality.
- **Pillars** (the topic mix the slate editor balances): `how_it_works` (one rule or system, evergreen: Know Your
  Government Shorts and Built to Fail long-forms), `now_explained` (a current story through its system),
  `myths_factchecks` (a false claim corrected with the record).
Audience: Filipinos in the Philippines and abroad, 18 to 45, curious, tired of noise, wanting to understand.

## 2. Voice (the part the pilot got right)
- A calm, clear male narrator in his early thirties: a good journalist or teacher explaining something important
  to someone he respects. Warm, steady, unhurried, quietly concerned. Never shouts, never sneers, never preachy.
- **Taglish narration** the way an educated Manila explainer actually speaks: Tagalog for the flow and the
  meaning, English for legal terms, institutions, numbers and quotes ("kailangan ng at least one-third ng lahat
  ng miyembro ng House").
- **Complete sentences that flow into each other**, usually 8 to 25 words. Each sentence carries one idea and
  moves the explanation forward. A short sentence is allowed only as the payoff after a full setup ("Sa ngayon,
  wala pang presidente ng Pilipinas na natanggal sa ganitong paraan.").
- **Teach with the real rule.** Name the source out loud the first time ("ayon sa Article 11, Section 3 ng 1987
  Constitution"), give the exact threshold or number, and say what it means in practice.
- **Numbers are said in English** and written as digits in the script ("₱170,598", "2026", "30 days"); the
  engine reads them the way Manila explainers do ("one hundred seventy thousand five hundred ninety-eight
  pesos", "twenty twenty-six"). Never Tagalog number words. Fractions in words ("one-third").
- **A number and its unit are in the same language**, the way Filipinos speak ("seven months", never "seven
  buwan"): "sa loob ng 7 months ng 2026", "mula January hanggang July 2026", "sa 7th month", "July 15, 2026", "₱1.37 trillion",
  "55.9%". A question about what will happen uses the contemplated aspect ("Babayaran mo ba iyon?"). "yung" for
  "the/that [thing]" and "[thing] mo" for "your", never "iyong" (Bryce, 2026-11-25); "sa iyo" and "iyon" stay.
  No vlog particles (eh, "di ba") and no textbook words (subalit, upang). Sources and before and after
  pairs: Bryce-Brain `wiki/answers/tfs-natural-taglish-2026-11.md`; machine checks in `src/tfs/taglish_lint.py`.
- **Questions, not slogans.** Open with the question the viewer has, and return to it at the end with what they
  now know.
- Compare fairly: the other country is an example of a different design, not a fantasy. Say its weak points too
  when they matter.

### Never
- No skits, characters or character voices, staged scenes, numbered episode rituals, running gags, catchphrases
  or recurring sign-off lines. Every line is a complete explanatory sentence.
- No exclamation marks, no stacked fragments, no counting used in place of explanation (numbered steps are
  fine when each step teaches the rule), no ironic one-liner turns.
- No em-dashes or en-dashes anywhere: they become on-screen captions. Use a comma or a full stop.
- No sarcasm aimed at people; no mockery of any group; no hype words (grabe, legit, shocking) as filler.

## 3. Hard rules (unchanged, enforced by the fact-checker)
1. **Naming:** name people only for history or a FINAL court conviction (cite it). Allegations, hearings, audits
   and ongoing cases use roles only ("isang senador", "the contractor"). Never add details that point to one person.
2. Every factual claim needs two independent credible sources or one primary source (the Constitution, a law, a
   court decision, a Senate or House record, a COA report); otherwise it is cut. "Ayon sa..." until a court rules.
3. No doxxing, no private individuals, no family members who hold no office.
4. All written text (cards, captions on screen, titles, descriptions, thumbnails, stamps and labels) is original
   English in complete, natural sentences; only the narration and its subtitles are Taglish. The one exception
   is YouTube tags, which are hidden search terms and may include the Tagalog or Taglish phrases people type.
5. AI voice is disclosed per platform rules. The narrator never claims to be a human expert or a real person.

## 4. Pictures (atlas engine)
Paper map of the Philippines, the exact text of laws on paper with a red circle and highlights, cards and charts
for every number the narrator says, real photographs of places and objects (Wikimedia Commons, public domain,
CC0 or CC BY, credited on screen), and one 3D push into Metro Manila in long-forms. There are no drawn characters.
