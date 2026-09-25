# Methodology

How Haqiqat turns thousands of reports into a small number of stories, and how every label
on a story page is decided. Every number below is a setting in `config/config.yaml`; the
values given are the defaults.

## 1. Sources

Every outlet has a file in `sources/` (see [source-rating.md](source-rating.md)) that
records:

- **Ownership and funding**, with evidence.
- **Independence group.** Outlets under common ownership or control share a group. BBC World
  and BBC Persian are one group. Radio Farda and VOA Persian (both USAGM-funded) are one
  group. Arab News and Independent Persian (both Saudi Research and Media Group) are one
  group. Anadolu and TRT World (both Turkish state) are one group.
- **Lenses.** The outlet's position on region-specific axes (`config/lenses.yaml`). Each
  position belongs to a **camp**.
  - **For stories about Iran**, the camps are:
    - *Inside Iran's system*: state, principlist, reformist and non-factional domestic media,
      all operating under the Islamic Republic's licensing and censorship.
    - *Persian media abroad*: foreign state-funded Persian services and privately owned
      diaspora media.
    - *Rights monitors.*
  - **For other stories, and for outlets without an Iran position**, the camp is the origin
    and funding bloc: Western, Israeli, Saudi/UAE, Qatari, Turkish, Russian, Chinese, and
    so on.

Iran's state media are split into several independence groups on purpose: the government
(IRNA), IRIB under the Supreme Leader (IRIB News, Press TV), IRGC-affiliated outlets (Tasnim,
Fars) and the Islamic Propagation Organization (Mehr, Tehran Times). They answer to different
centres of power. They all sit in one camp, though, so they can never "confirm across sides"
among themselves.

## 2. Collection

- RSS/Atom feeds and Google News sitemaps only. robots.txt is respected, requests carry a
  clear user agent, there is at least a 1 s delay per host, and requests are conditional
  (ETag / Last-Modified).
- Main text is extracted for analysis and stored privately. We publish only headlines, short
  excerpts, links and our own summaries. We never circumvent paywalls. Outlets can ask to be
  removed.

## 3. Processing (no LLM)

1. **Normalization.** Persian and Arabic letter variants (ي/ی, ك/ک), digits and
   zero-width characters are unified for matching. Display text keeps its original form.
2. **Language check.** Script-based, against the feed's declared language.
3. **Near-duplicates.** Articles are compared with MinHash over 3-word shingles, within 72
   hours. An estimated Jaccard similarity of 0.7 or more, with at least 25 tokens, marks an
   article as a *copy* of the earlier one. A copy joins the original's story and inherits
   the original's independence group, so syndication never adds confirmations.
4. **Embeddings.** Each non-copy article's title and lead are embedded with a multilingual
   model. The results are cached by content hash.
5. **Stories.** Each article joins the most similar open story (cosine similarity to the
   story centroid of at least `join_threshold`, within 72 hours) if they are
   *place-compatible*. Place-compatible means they share a country, or one side has no
   detected place. Above `strong_threshold` an article joins even without a shared place.
   Otherwise it starts a new story. Stories whose centroids converge (similarity of 0.80 or
   more) are merged.
6. **Storylines.** A story links to an earlier story from the last 30 days when their
   similarity is at least `storyline_threshold` and they share a country. Linked stories form
   a storyline, such as "Iran nuclear talks".
7. **Places and regions.** A bilingual gazetteer finds countries in titles and leads. A story
   is *about* the countries that at least 30% of its articles mention. Regions follow from
   the countries (`config/regions.yaml`).
8. **Topic.** Zero-shot classification against the IPTC Media Topics top level, by
   similarity between the story centroid and each topic's description.

## 4. Ranking (every run, no LLM)

```
score = ( 1.0 · log2(1 + independent_groups)
        + 0.8 · lens_diversity        # (camps − 1) / 2, capped at 1
        + 0.3 · geo_scope             # log2(1 + countries) / 2.5, capped at 1
        + 0.5 · velocity              # groups joining in the last 6 h / 5, capped at 1
        + 0.6 · impact                # LLM impact 0–10, divided by 10 (0 before any summary)
        + 0.3 · confirmation )        # share of facts that are confirmed or corroborated
        × 0.5 ^ (hours since the latest article / 18)
```

No clicks, shares, dwell time or any other engagement signal is used, now or later.

## 5. When the LLM runs

The LLM *reads*; code *counts*.

- **First summary.** A story is summarized once it is *mature*: it has at least 2
  independent groups and is among the top 50 by score. Stories that gain 3 or more groups
  within an hour are fast-tracked.
- **New versions.** A story gets a new version only on *material change*:
  - a new independence group joined
  - the article count grew by 50% or more since the last version
  - a new article is *novel*, meaning its embedding is far (below 0.55) from every article
    the current facts cite
- **Limits.** Re-summaries are debounced (2 h for the top 15 stories, 12 h for the rest)
  and capped at 4 versions per story per day.
- **Budget.** The day's budget goes to candidates in order of `score × (1 + size of change)`.
  A call is skipped if its estimated cost exceeds what remains. Skipped stories use the
  extractive fallback (§7).
- **Inputs.** One article per independence group, earliest first, rotating across camps.
  At most 8 articles for a new story and 6 for an update. Each is sent as its title plus the
  first 1,200 characters.
- **Updates are incremental.** An update sends the previous facts (with their ids) and only
  the new articles. For each existing fact, the model lists which *new* articles support or
  contradict it. Code merges those lists into the stored ones.
- **Output.** Structured JSON, validated against a schema:
  - neutral title and summary in English and Persian
  - facts, each with a kind, who it is attributed to, and supporting and contradicting
    article references
  - disputes, with each side's position and articles
  - an impact score from 0 to 10
- **Rejected output.** Facts without citations are discarded. Loaded terms from
  `config/style.yaml` that appear in our own text are recorded as `style_flags` for review.
- **Stored.** Every version is stored with its model, prompt version, input article ids,
  token counts and cost, and the story page shows these.

The prompts are in `src/haqiqat/prompts/`. Changing them means changing `PROMPT_VERSION`, so
outputs from different prompts are never confused.

## 6. Fact labels (code, not AI)

For each fact, code looks up the independence groups and camps of the articles supporting
it:

| Label | Rule |
|---|---|
| **Disputed** | At least one article contradicts it |
| **Widely confirmed** | At least 3 independent groups across at least 2 camps |
| **Confirmed across sides** | At least 2 independent groups across at least 2 camps |
| **Reported by one side** | At least 2 independent groups, all in one camp |
| **Single source** | 1 independent group |

The fact's *kind* is shown separately: an **event**, a **statement** (what a named party
said), a **claim** (an assertion others dispute or that cannot be checked) or a **figure**
(a number, with who gives it). A statement can be "widely confirmed" in the sense that many
outlets report that the party *said* it. That confirms the statement was made, not that its
content is true. Pages always show who it is attributed to.

**Blindspot.** When a story has at least 4 independent groups and at least 80% of them are in
one camp, the page names the camp that dominates its coverage.

## 7. Fallback without an LLM

Mature stories without an LLM summary still get published, with sentences several
independent groups share. These are quoted verbatim in each page language and ranked by how
many groups have a similar sentence (token Jaccard of 0.25 or more). Opinion markers are
filtered out and near-repeats removed. If no such sentence exists, the page shows the
headlines as published.

## 8. Publishing

- **Website.** Static and bilingual (Persian RTL), with a Solar Hijri calendar for Persian
  pages, region pages, story and storyline pages, a sources page, JSON data and RSS. Story
  pages are never deleted, and merged stories redirect to the surviving story.
- **Telegram.** One channel per language. Stories with an LLM summary and a score of at
  least 2.0 are posted, at most 12 per day per channel. New versions edit the existing post
  (within 48 h) instead of posting again. A daily digest goes out at 20:00 Tehran time.

## Known limitations

- The seed source list and its labels are a starting point written by maintainers. They need
  review, evidence and more voices (see [source-rating.md](source-rating.md)).
- Embedding models vary in how well they handle Persian. Check yours with
  `haqiqat eval-embeddings` and tune `join_threshold`.
- The LLM can still misread an article. Mitigations:
  - citations are mandatory
  - labels come from code
  - every page links every source
  - corrections are logged in the repository's issues
- Outlets that publish mainly on Telegram, and `.ir` sites unreachable from abroad, are
  covered less well until the Telegram and GDELT collectors land (see [roadmap.md](roadmap.md)).
