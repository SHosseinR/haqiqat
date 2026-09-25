# Haqiqat · حقیقت

**News from every side. Facts traced to their sources.**

[فارسی](README.fa.md)

Haqiqat is an open-source news platform that is **not a news agency**. It does no reporting of
its own. It:

- collects reports from outlets on every side (state and official media, principlist and
  reformist outlets, Persian-language media abroad, human-rights monitors, and regional and
  international media)
- groups reports about the same event, across languages
- separates what is **independently confirmed** from what **one side claims** and what is
  **disputed**
- ranks stories by significance, never by clicks
- publishes to a bilingual website (English and Persian) and to Telegram channels

Nobody is unbiased, so Haqiqat does not claim to be. It shows provenance instead: every
statement links to the reports behind it, and every rule is public. The code, the source list
and its evidence-backed labels, the prompts, the ranking formula and every AI output are all
open.

The first scope is West Asia (Iran first) plus major global events. New regions and languages
are added as configuration and data, not code.

## How it works

```
sources/*.yaml ─► ingest (RSS + news sitemaps) ─► extract text ─► normalize / language
  ─► near-duplicate detection (MinHash) ─► embeddings (API, cached)
  ─► cluster into stories → storylines ─► topic (IPTC) + places
  ─► rank (every run, no LLM) ─► pick stories that need a summary (maturity + material change + budget)
  ─► LLM synthesis / incremental update (or free extractive fallback) ─► fact labels (code)
  ─► static site (EN/FA) · Telegram · JSON / RSS
```

The LLM does the reading; code does the counting.

- **Stories.** An article joins the most similar open story (multilingual embeddings, so an
  English and a Persian report of the same event merge). Coverage, rank and blindspot flags
  update on every run at no cost.
- **Summaries.** A story gets an LLM summary only once it is *mature*: it has at least 2
  independent sources and is in the top K. It gets a new *version* only on *material change*: a
  new independent source or perspective, strong growth, or a report with new information.
  Updates send only the new articles plus the previous facts. The model says which new
  articles support or contradict each fact.
- **Labels.** Labels such as "widely confirmed", "confirmed across sides", "reported by one
  side", "single source" and "disputed" are computed by code from **independence groups**
  (outlets with a shared owner count once, and syndicated copies count once) and **camps**
  (see `config/lenses.yaml`).
- **Budget.** A hard daily cap on spending. When the cap is reached, stories fall back to a
  free extractive summary built from sentences several independent outlets share.

Details: [docs/methodology.md](docs/methodology.md) · [docs/architecture.md](docs/architecture.md)

## Quick start

```bash
# Python 3.11+, uv (https://docs.astral.sh/uv/)
uv sync
cp config/config.example.yaml config/config.yaml   # then edit

# Offline dry run with fake AI providers (no keys needed; needs network for feeds)
uv run haqiqat run --once --limit-sources 10 --llm fake --embeddings fake
python -m http.server -d build/site 8000            # open http://localhost:8000

# Real run
export OPENAI_API_KEY=...        # embeddings (any OpenAI-compatible provider works)
export ANTHROPIC_API_KEY=...     # synthesis (or point `stages` at another provider)
uv sync --extra anthropic
uv run haqiqat eval-embeddings   # check the embedding model separates EN/FA same-event pairs
uv run haqiqat run --once
uv run haqiqat costs
```

Useful commands:

| Command | What it does |
|---|---|
| `haqiqat validate-sources [--probe]` | Validate every source file; with `--probe`, fetch every feed |
| `haqiqat run --once` | Ingest, process, synthesize, build the site, publish (for cron or systemd) |
| `haqiqat synthesize --max-calls 5` | Only the LLM step, capped |
| `haqiqat publish-telegram --dry-run` | Print the Telegram posts instead of sending them |
| `haqiqat costs` | Spend by day, stage and model |
| `haqiqat export-schema` | Regenerate `sources/schema.json` |

Deploying on a small VPS (about €4–5 a month) with a systemd timer:
[deploy/README.md](deploy/README.md).

## Providers

Every stage names its provider in `config/config.yaml`:

- **`openai_compat`**: any OpenAI-compatible API, for chat and embeddings. Examples: OpenAI,
  Mistral, OpenRouter, DeepSeek, Groq, and self-hosted Ollama or vLLM.
- **`anthropic`**: the native Claude API, for chat. It uses prompt caching and server-side
  refusal fallbacks.
- **`local`**: local embeddings with sentence-transformers.

Embeddings default to an API because that is cheaper than a server with enough RAM for a
local model.

## Project status

This is an early MVP. See [docs/roadmap.md](docs/roadmap.md).

**The seed feed URLs in `sources/` are unverified** (all marked `verified: false`). They were
written without network access to the outlets. Run `haqiqat validate-sources --probe` on your
server, fix or replace failing URLs, and set `verified: true`.

## Contributing

- Add or correct a source with a pull request to `sources/`.
- Every ownership, lens or reliability label needs evidence; see
  [docs/source-rating.md](docs/source-rating.md).
- For code, see [CONTRIBUTING.md](CONTRIBUTING.md).
- Pseudonymous contributions are welcome.

## License

- Code: [AGPL-3.0](LICENSE). If you run a modified public copy, you must publish your changes.
- Data, documentation and methodology: [CC BY-SA 4.0](LICENSE-DATA).
