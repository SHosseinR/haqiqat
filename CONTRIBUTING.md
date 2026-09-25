# Contributing

Thank you for helping. Pseudonymous contributions are welcome: use any name and email you
like in your git config. Contributors inside Iran should consider their own safety first.

## Ways to help

- **Sources.** Add outlets, fix feed URLs, and improve ownership or lens labels with evidence.
  Read [docs/source-rating.md](docs/source-rating.md) first.
- **Evaluation data.** Add labeled same-event and different-event pairs to
  `tests/data/pairs.yaml`, especially English–Persian ones.
- **Style.** Improve the neutral-wording glossary (`config/style.yaml`,
  [docs/style-guide.md](docs/style-guide.md)).
- **Code.** See [docs/architecture.md](docs/architecture.md) and the roadmap.

## Development

```bash
uv sync                      # Python 3.11+
uv run pytest                # offline, no keys needed
uv run ruff check .
uv run haqiqat validate-sources
uv run haqiqat run --once --llm fake --embeddings fake --limit-sources 5
```

- Keep the pipeline cheap: rules and classical methods before embeddings, and embeddings
  before an LLM.
- Anything that decides a label or a rank must be deterministic code, with its rule
  documented in [docs/methodology.md](docs/methodology.md).
- When you change a prompt, bump `PROMPT_VERSION` in `src/haqiqat/synthesize.py` and add the
  new prompt files. Never edit a released prompt in place.
- New tests should run offline (see `tests/conftest.py` for the mock web and fake
  providers).

By contributing you agree that code is licensed under AGPL-3.0, and data and documentation
under CC BY-SA 4.0.
