# Rating sources

Source labels are the most contestable part of Haqiqat. They are therefore public data,
changed only through public pull requests, and every label must cite evidence.

## What a source file contains

See `sources/schema.json` for the full schema (regenerate it with `haqiqat export-schema`).

```yaml
id: arab-news                      # file name must match
name: {en: Arab News, fa: عرب نیوز}
homepage: https://www.arabnews.com
languages: [en]
country: SA                        # where it is based (ISO 3166)
type: newspaper                    # news_agency | newspaper | broadcaster | online | wire |
                                   # monitor | government | intergovernmental
ownership:
  kind: private                    # state | public | private | nonprofit | party | unknown
  state: null                      # ISO code of the state that owns/funds it, if any
  owner: Saudi Research and Media Group
  evidence:
    - {url: https://en.wikipedia.org/wiki/Arab_News, note: Wikipedia article}
independence_group: srmg           # shared by every outlet under the same owner/control
lenses:                            # positions from config/lenses.yaml
  origin: saudi_uae
reliability:
  wikipedia_en: unreviewed         # generally_reliable | no_consensus | generally_unreliable |
  wikipedia_fa: unreviewed         # deprecated | not_listed | unreviewed
feeds:
  - url: https://www.arabnews.com/rss.xml
    kind: rss                      # or sitemap
    verified: false                # true once `haqiqat validate-sources --probe` passes
```

## Rules for labels

1. **Evidence or it doesn't go in.** Ownership, funding, independence groups and lens
   positions need at least one public source: a Wikipedia article with citations, a company
   registry, the outlet's own "about" page, State Media Monitor, or academic research. Link
   it under `evidence`.
2. **Describe structure, not virtue.** Labels say who owns an outlet, who funds it and which
   system it operates in. They never say whether it is "good". Reliability references point
   to external community processes (Wikipedia's perennial sources lists in English and
   Persian) rather than to our own judgment.
3. **When in doubt, group together.** If two outlets may share control, putting them in one
   independence group is the safer error: it under-counts confirmation instead of inflating
   it. Record the doubt in `notes`.
4. **Contested funding claims are notes, not labels.** Where funding is alleged but denied
   (for example, reported Saudi links to Iran International, or reported Qatari links to
   Middle East Eye), record the claim and its sources in `notes`. Change `ownership` only
   when the evidence is solid.
5. **Positions are about the system, not opinions.** On the Iran axis, "inside" means an
   outlet operates under the Islamic Republic's licensing and censorship, whatever its
   faction. Reformist papers are "inside"; that describes their constraints, not their views.
6. **Symmetry.** Apply the same standard to every side. State media of every country is
   labeled as state media.

## How changes are made

- Open a pull request that edits the source file and explains the change, with evidence.
- CI validates the schema. Maintainers review for evidence and symmetry.
- Disagreements are discussed in the pull request, in public. If reviewers cannot agree,
  record the disagreement in `notes` and keep the more conservative label.
- Every change is in the git history. Labels are never edited silently.

## Adding a new outlet

1. Copy an existing file in the same folder and edit it.
2. Run `uv run haqiqat validate-sources --probe` locally to check the schema and the feeds.
3. Set `verified: true` on feeds that returned items.
4. Open a pull request.

Outlets that publish mainly on Telegram will be supported by the Telegram collector (see
[roadmap.md](roadmap.md)). Until then, open an issue with the channel link so it is on the
list.
