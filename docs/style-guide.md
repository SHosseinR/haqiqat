# Style guide: neutral wording in English and Persian

This applies to everything Haqiqat itself writes: AI summaries, facts, titles, Telegram posts
and interface text. Quotes and headlines from sources are shown as published, always
attributed.

## Core rules

1. **Attribute, don't assert.** "Iran's foreign ministry said…" / «وزارت خارجه ایران
   گفت…». Something is written as plain fact only when independent sources on different
   sides report it.
2. **Plain verbs of saying.** Use *said, stated, announced, reported* / «گفت، اعلام کرد،
   گزارش داد». Avoid verbs that judge: *admitted, claimed* (as a sneer), *slammed, blasted* /
   «اعتراف کرد، مدعی شد (با طعنه)، تاخت».
3. **Numbers keep their source.** "At least 12 killed, according to state media; 31
   according to Hengaw" / «دست‌کم ۱۲ کشته به گزارش رسانه‌های رسمی؛ ۳۱ کشته به گزارش
   هه‌نگاو». Never average or reconcile conflicting figures.
4. **Name actors as they are commonly and officially named**, and attribute contested
   labels to whoever uses them.
5. **No clickbait, no questions as headlines**, no adjectives that tell the reader how to
   feel.

## Glossary

| Avoid (our own voice) | Use instead | Persian: avoid | Persian: use |
|---|---|---|---|
| regime | the government; the Islamic Republic; the [country] government | رژیم | حکومت، دولت، جمهوری اسلامی |
| Zionist entity / Zionist regime | Israel | رژیم صهیونیستی | اسرائیل |
| martyred | killed | شهید شد / به شهادت رسید | کشته شد |
| rioters, thugs | protesters (attribute if a party calls them rioters) | اغتشاشگران، آشوبگران | معترضان (با نقل قول از طرفی که این عنوان را به کار می‌برد) |
| terrorists (unattributed) | name the group; "which X designates as a terrorist organization" | تروریست‌ها (بدون انتساب) | نام گروه؛ «که ... آن را تروریستی می‌داند» |
| mullahs | clerics; officials | آخوندها | روحانیان؛ مقام‌ها |
| sedition (for protests) | protests (attribute the label) | فتنه | اعتراضات (با نقل قول) |
| brutal, heroic | describe what happened | وحشیانه، قهرمانانه | شرح آنچه رخ داد |
| so-called | name it; attribute any label | به اصطلاح | نام آن؛ انتساب هر برچسب |

`config/style.yaml` holds the machine-checked list. Summaries that contain these terms are
flagged (`style_flags` in the story JSON) for maintainers to review and to improve the prompt.

## Persian orthography

- Use the zero-width non-joiner (نیم‌فاصله): «می‌گوید»، «گزارش‌ها»، «هسته‌ای».
- Use Persian letters (ی، ک), not Arabic (ي، ك).
- Pages use Persian digits (۰–۹); data files and the API use ASCII digits.
- Persian pages show dates in the Solar Hijri calendar and times in Tehran time.
