# Landscape: what exists and what we reuse

Research notes from the planning phase (September 2026). Corrections welcome.

## Similar products

| Project | What it does | Open? | Lesson for Haqiqat |
|---|---|---|---|
| [Ground News](https://ground.news) | Clusters stories; left/center/right coverage bars; "Blindspot"; ownership and factuality labels (built from AllSides, Ad Fontes and MBFC ratings) | Closed, paid | The blindspot idea is excellent. A US left/right axis is useless for Iran. |
| [Kagi News](https://github.com/kagisearch/kite-public) (Kite) | Daily LLM summaries of clustered stories, from RSS only | Frontend MIT, feed lists CC BY-NC; backend, clustering and LLM pipeline closed | Use RSS only; accept community feed PRs; a calm daily cadence. |
| [News Minimalist](https://newsminimalist.com) | LLM gives each article a significance score from 0 to 10 (about 30k articles/day) | Closed | Significance ranking is valuable, but a black box. We publish the formula. |
| [Verity](https://www.improvethenews.org) (Improve the News) | Sliders for left/right and pro/anti-establishment | Closed | The establishment axis maps well onto Iran (inside vs. outside the system). |
| [AllSides](https://www.allsides.com) | Human bias ratings, side-by-side views | Ratings CC BY-NC | NC is incompatible with our CC BY-SA data; reference only. |
| MBFC, Ad Fontes, NewsGuard | Proprietary outlet ratings | Closed | Do not depend on them. |
| [Groundish News](https://github.com/Just-Rice/groundish-news) | Open Ground News clone: TF-IDF clustering, extractive consensus summaries, blindspots, static GitHub Pages site | Code public (no license stated) | Proves a cheap static design works. Lexical clustering cannot match English with Persian. Its extractive idea is our fallback. |
| [Media Cloud](https://www.mediacloud.org) | Research platform with 60k+ sources and 2B+ stories | Open source | Source directory and methods to learn from; a research tool, not a reader product. |
| Balatarin, Gooya News, Akharin Khabar, Khabarfarsi | Persian aggregators and link-sharing sites | — | None has a bias or verification layer. **That gap is ours.** |

## Data and components we reuse

| Need | What we use | License | Notes |
|---|---|---|---|
| Feed parsing | `feedparser` | BSD | RSS/Atom |
| Main-text extraction | `trafilatura` | Apache-2.0 | Multilingual. We protect Persian ZWNJ, which it would otherwise strip. `fundus` (MIT) is more precise for the sites it supports. |
| Multilingual embeddings | Any OpenAI-compatible embeddings API; `BAAI/bge-m3` locally | MIT (bge-m3) | Must match English and Persian reports of the same event; check with `haqiqat eval-embeddings`. |
| Topic taxonomy | [IPTC Media Topics](https://iptc.org/standards/media-topics/) | CC BY 4.0 | The news industry's standard hierarchy. |
| Places | Hand-built bilingual gazetteer; [GeoNames](https://www.geonames.org) later | CC BY | Region tagging without an LLM. |
| Source reliability | [Wikipedia perennial sources](https://en.wikipedia.org/wiki/Wikipedia:Reliable_sources/Perennial_sources), English **and Persian** | CC BY-SA | Same license family as our data; the Persian list is actively maintained. |
| State-media labels | [State Media Monitor](https://statemediamonitor.com) (CEU) | Open access | Classifies 546 state media outlets by funding, governance and editorial autonomy. |
| Discovery and backfill (later) | [GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) | Open data | Machine-translates 65+ languages including Persian; free. |
| Fact-checks (later) | Google Fact Check Tools API (ClaimReview); Persian fact-checkers | Open API | Attach existing fact-checks to claims. |
| Telegram as a source (later) | Public channel previews (`t.me/s/…`) or MTProto clients | — | Many Iranian officials and outlets post there first. |

## The Iran context (2026)

- Iran's internet was shut down from January 8 to May 26, 2026, including 88 days with no
  global internet access at all. Access since then has been tiered: international services
  are reachable mainly through paid "Internet Pro" plans or circumvention tools.
- Consequences for Haqiqat:
  - Telegram is the most practical way to reach readers inside Iran.
  - The website must be light and easy to mirror.
  - Some `.ir` sites are unreachable from abroad at times. We document such coverage gaps
    openly and add further fetch paths (Telegram previews, GDELT).
