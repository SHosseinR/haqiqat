# Architecture

Built for one operator on a tiny server: one Python process run by a timer, one SQLite file,
a static site, and APIs for the heavy lifting.

```
sources/*.yaml ─► ingest.py ─► cluster.py ───────────────► rank.py
                  RSS/sitemaps  normalize, lang, MinHash    formula, every run
                  robots.txt    embed.py (API + cache)
                  trafilatura   stories → storylines
                                places, IPTC topic
                                         │
                                         ▼
                  lifecycle.py ─► synthesize.py ─► labels.py ─► publish/site.py
                  maturity,       LLM (structured)   code rules    static EN/FA
                  material change incremental update               publish/telegram.py
                  budget order    budget.py cap                    JSON / RSS
                                  extractive.py fallback
```

## Modules (`src/haqiqat/`)

| Module | Responsibility |
|---|---|
| `config.py` | Typed configuration (pydantic) loaded from YAML |
| `sources.py` | Source registry and lenses; validation; JSON schema |
| `db.py` | SQLite schema and helpers |
| `ingest.py` | Feeds, news sitemaps, robots.txt, politeness, text extraction |
| `nlp/` | Normalization, language, MinHash, gazetteer, topic classifier |
| `embed.py` | Embeddings with a content-hash cache and spend records |
| `cluster.py` | Dedup, online story clustering, merging, storylines, attributes |
| `coverage.py` | Independence groups and camps per story (the heart of "independent") |
| `rank.py` | Published ranking formula |
| `lifecycle.py` | When to summarize and when to make a new version |
| `synthesize.py` | Prompts, structured output, incremental merge, storage |
| `labels.py` | Fact labels and blindspots from coverage rules |
| `extractive.py` | Free fallback summary |
| `providers/` | `openai_compat`, `anthropic` (native Claude), `local`, `fake` |
| `budget.py` | Cost accounting and the daily cap |
| `views.py` | Read models shared by the site and Telegram |
| `publish/` | Static site (Jinja2), Telegram, feeds |
| `cli.py`, `pipeline.py` | Commands and wiring |

## Data model (SQLite)

- `articles`: one row per URL. Holds the extracted text (private), language, MinHash,
  `dup_of`, embedding (plus the model that made it), `story_id` and countries.
- `stories`: centroid, counts, places, regions, category, score and its parts, current
  version, and a snapshot of the articles and groups known at the last version.
- `storylines`: groups of related stories.
- `syntheses`: every version of every summary, with trigger, model, prompt version, input
  article ids, output JSON, tokens and cost.
- `llm_usage`: every model call (embeddings included), used for the daily cap and
  `haqiqat costs`.
- `embedding_cache`, `feed_state`, `publications` (Telegram posts and digests).

Every vector records its model. Switching embedding models only requires re-embedding the
active 72-hour window, because older stories are closed.

## Providers

Every LLM stage (`synthesize`, `update`) and the embeddings name a provider and model in
config. Backends:

- **`openai_compat`**: chat completions with `response_format` (JSON schema or JSON object,
  configurable), plus `/embeddings`. Works with OpenAI, Mistral, OpenRouter, DeepSeek, Groq,
  Together, Ollama, vLLM and others.
- **`anthropic`**: the official SDK. It uses `output_config.format` for structured output, an
  optional `effort` setting, prompt caching of the stable system prompt, and server-side
  refusal fallbacks (`fallbacks: default`).
- **`local`**: sentence-transformers embeddings (optional extra).
- **`fake`**: deterministic offline providers for tests and dry runs.

## Costs (rough, MVP volume)

About 80 sources give roughly 2–4k articles/day and 300–600 stories/day. Of those, about 50
get LLM summaries, for about 100 calls a day including updates.

- **Embeddings.** About 2M tokens a day, which costs cents per day on a small embeddings
  model.
- **Synthesis.** Each call is about 4.5k input and 1.2k output tokens, plus thinking
  tokens where the model uses them. Priced per 1M input/output tokens:
  - Claude Haiku 4.5 ($1/$5): about $1 a day
  - Claude Sonnet 5 ($2/$10): about $2 a day
  - Claude Opus 5 ($5/$25): about $5 a day

  The daily cap (`budget.daily_usd`) bounds spend whatever the model.
- **Server.** A €4–5/month VPS with 2 GB RAM is enough when embeddings run through an API.
  Static hosting (Cloudflare Pages or GitHub Pages) is free.

## Testing

`uv run pytest` runs everything offline: fixture feeds served by a mock HTTP transport,
fake embeddings with a tiny bilingual lexicon (so cross-lingual clustering logic is
exercised), and a fake LLM. It covers:

- dedup, clustering, labels and incremental merges
- lifecycle triggers and the budget cap
- site output and Telegram previews
- provider request shapes

A real multilingual model is checked separately with `haqiqat eval-embeddings`.
