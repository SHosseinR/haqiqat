These {{ articles|length }} articles, from {{ n_groups }} independent sources, report the same event. For each article you get: reference, outlet, ownership, language, publication time (UTC), title and opening text.
{% for a in articles %}
[{{ a.ref }}] {{ a.source }} | {{ a.ownership }} | {{ a.lang }} | {{ a.published }}
Title: {{ a.title }}
Text: {{ a.lead }}
{% endfor %}
Write the story JSON: title, summary, facts (ids F1, F2, …), disputes and impact.
