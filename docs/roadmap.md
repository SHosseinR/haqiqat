# Roadmap

## Phase 0: MVP (this release)

- [x] Vision, landscape, methodology, source-rating and style-guide docs
- [x] Source registry: 65 outlets across every camp, lenses, independence groups, JSON schema
- [x] Ingestion: RSS and news sitemaps, robots.txt, text extraction that keeps Persian ZWNJ
- [x] Processing: normalization, MinHash dedup, API embeddings with a cache, cross-lingual
      story clustering, merging, storylines, IPTC topics, places and regions
- [x] Transparent ranking formula
- [x] Lifecycle: maturity, material change, debounce, budget-ordered spending
- [x] LLM synthesis with incremental updates. Providers: OpenAI-compatible, native Claude,
      local, fake
- [x] Code-computed fact labels, blindspots, extractive fallback
- [x] Static bilingual site (RTL, Solar Hijri dates), JSON, RSS
- [x] Telegram channels: posts, in-place edits, daily digest
- [x] Offline test suite, CI, deploy files

**Before going live:**

- [ ] Run `haqiqat validate-sources --probe` on the server, fix feed URLs and set
      `verified: true`
- [ ] Run `haqiqat eval-embeddings` with the chosen provider and set `join_threshold`
- [ ] Review the seed labels with evidence, especially Iranian outlets' positions
- [ ] Create the Telegram channels and bot, set `telegram.enabled: true`

## Phase 1: hardening (month 1–2)

- A larger evaluation set: about 200 real labeled article pairs (EN–EN, FA–FA, EN–FA) and
  summary spot checks
- Corrections log and a "report a problem" link on every story
- Storyline timelines with their own titles
- Better entity extraction (GLiNER multilingual in the `local` extra; entities from synthesis
  otherwise) for place and actor matching
- Optional "verify" stage: a cheap per-article check that updates fact labels between full
  re-summaries, for top stories only
- Daily open-data dumps, a cost dashboard, self-hosted Persian web font
- Pagefind static search

## Phase 2: more coverage (month 2–4)

- **Telegram as a source**: public channel previews (`t.me/s/…`). Many Iranian officials and
  outlets publish there first.
- GDELT DOC API for discovery and for `.ir` sites unreachable from abroad
- Arabic, Hebrew and Turkish input, translated inside the synthesis step
- Fact-check links (ClaimReview, Persian fact-checkers)
- Reader-side ranking sliders (for example, more weight on diversity)
- Mirrors: a Tor onion service and IPFS, plus a lightweight daily digest page that is easy
  to forward

## Phase 3: grow (month 4+)

- More regions and output languages (Arabic first)
- A PWA or app, email digest
- Governance: a nonprofit home, a multi-camp advisory group for source labels, and
  transparent funding (no state money)
