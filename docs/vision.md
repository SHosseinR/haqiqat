# Vision

## The problem

Every news organization is biased. The bias can come from its owners, its funders, its
country, its faction or its audience. Readers who want to be informed rather than persuaded
have to read many outlets from many sides and reconcile them by hand. Almost nobody has time
for that.

Aggregators exist that try to do this work: Ground News, AllSides, News Minimalist, Verity,
Particle and Kagi News. All of them keep their core closed: how they cluster stories, how they
rank them, how they rate outlets, and what their AI is told to do. A reader has to trust them
without being able to check. Their bias model is also usually the US left/right axis, which
says little about Iran or the wider Middle East, where the lines run between state and
diaspora, between factions inside a political system, and between regional powers.

Persian-language readers have no transparent, multi-perspective aggregator at all.

## What Haqiqat is

- **Not a news agency.** We do no reporting of our own. We read what others publish.
- **A merger of perspectives.** Reports from every side of a story are grouped together:
  official media, factional outlets, diaspora media, human-rights monitors, and regional and
  international outlets.
- **A separator of fact from claim.** For each story we show what several *independent*
  sources on *different sides* report, what only one side reports, and what is disputed,
  with every statement linked to its sources.
- **Ranked by significance, never by engagement.** No clicks, no outrage optimization.
- **Bilingual from day one.** Persian and English, with more languages added later as
  configuration and data.
- **Regional by design.** Readers choose a region of interest. The first scope is West Asia
  (Iran first) plus major global events.

## Trust through openness, not through claims

We don't claim to be unbiased. We make our biases inspectable:

1. **Open code** (AGPL-3.0). Anyone can run the same pipeline and compare the output.
2. **Open source list** (CC BY-SA). Who each outlet belongs to, which camp it sits in, and the
   evidence for each label. Changes go through public pull requests.
3. **Open rules.** The ranking formula and the fact-labelling rules are published and set in
   configuration.
4. **Open AI use.** Prompts are versioned in the repository. Every AI output is stored with
   its model, prompt version, inputs and cost, and every story page says how it was made.
5. **Code decides, AI reads.** The AI reports which articles support or contradict each
   fact. Whether that adds up to "confirmed" is a rule applied by code, the same way every
   time.

## Principles

- **Show provenance, don't claim neutrality.** Attribute, don't assert.
- **Independence, not volume.** Syndicated copies and outlets with the same owner count once.
- **Disagreement is information.** Conflicting figures are shown side by side, each with its
  source. We never average them.
- **Cheap first, AI last.** Rules, then classical methods, then embeddings, then an LLM, and
  only when it adds value.
- **Censorship-resilient.** Light static pages that are easy to mirror, and Telegram as a
  primary channel for readers inside Iran, where internet access is often restricted.
- **Safe to contribute.** Pseudonymous contributions are welcome. We do not track readers.

## Who it is for

- Readers inside and outside Iran who want to know what happened, and who says so.
- Journalists and researchers who need a transparent, citable map of coverage.
- Developers who want to fork the method for other regions and languages.
