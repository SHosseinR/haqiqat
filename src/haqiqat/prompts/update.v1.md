This story already has a published summary (version {{ previous.version }}). New articles have arrived. Update the story.

## Current version

Title (en): {{ previous.title.en }}
Summary (en): {{ previous.summary.en }}
Summary (fa): {{ previous.summary.fa }}

Facts (keep these ids):
{% for f in previous.facts %}
[{{ f.id }}] ({{ f.kind }}{% if f.attributed_to %}, according to {{ f.attributed_to }}{% endif %}) {{ f.text.en }}. Supported by: {{ f.sources }}
{% endfor %}
{% if previous.disputes %}
Known disputes:
{% for d in previous.disputes %}
- {{ d.topic.en }}
{% endfor %}
{% endif %}

## New articles ({{ articles|length }})
{% for a in articles %}
[{{ a.ref }}] {{ a.source }} | {{ a.ownership }} | {{ a.lang }} | {{ a.published }}
Title: {{ a.title }}
Text: {{ a.lead }}
{% endfor %}

## What to return

- `title` and `summary`: the full revised versions, including what the new articles add.
- `facts`:
  - Return each existing fact that a new article supports or contradicts, with its same id, listing **only new article references** under `supporting` and `contradicting`. You may improve its wording.
  - Add facts that only the new articles establish, with new ids starting at F{{ next_fact_id }}.
  - Existing facts you do not return are kept unchanged.
- `disputes`: only **new** disagreements that the new articles introduce, citing new article references.
- `impact`: your current estimate.
