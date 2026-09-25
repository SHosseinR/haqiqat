"""Interface strings and locale formatting for the site and Telegram posts."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .jalali import MONTHS_FA, jalali
from .nlp.normalize import to_persian_digits

UI: dict[str, dict[str, str]] = {
    "en": {
        "dir": "ltr",
        "tagline": "News from every side. Facts traced to their sources.",
        "top_stories": "Top stories",
        "independent_sources": "{n} independent sources",
        "ai_summary": "AI summary",
        "version": "version {v}",
        "key_facts": "Key facts",
        "disputes": "Disputed points",
        "coverage": "Who covered it",
        "all_reports": "All reports",
        "new_since": "{n} new reports since this summary ({time})",
        "blindspot": "Covered mainly by: {camp}",
        "headlines_only": "No summary yet. Headlines as published:",
        "extractive_note": "No AI summary yet. Sentences that several independent outlets share, "
                           "quoted as published:",
        "n_sources_short": "{n} sources",
        "about": "About & method",
        "sources": "Sources",
        "storyline": "More on this storyline",
        "other_lang": "فارسی",
        "according_to": "according to {x}",
        "provenance": "Written by {model} (prompt {pv}) from {n} articles. Labels are computed "
                      "by code from the sources, not by the AI.",
        "source_code": "Source code",
        "data": "Data (JSON)",
        "copy": "copy of an earlier report",
        "updated": "Updated {time}",
        "empty": "No stories yet.",
        "regions": "Regions",
        "significance": "Significance",
        "ownership": "Ownership",
        "group": "Independence group",
        "lenses": "Lenses",
        "reliability": "Reliability references",
        "country": "Based in",
        "feeds": "Feeds",
        "rss": "RSS",
        "choose_language": "Choose a language",
        "not_news_agency": "Haqiqat is not a news agency. It does no reporting of its own: it "
                           "collects reports from outlets on every side, groups them by event, "
                           "separates what is independently confirmed from what one side claims, "
                           "and links every statement to its sources.",
    },
    "fa": {
        "dir": "rtl",
        "tagline": "خبر از همهٔ سوها. هر واقعیت با منبعش.",
        "top_stories": "مهم‌ترین خبرها",
        "independent_sources": "{n} منبع مستقل",
        "ai_summary": "خلاصهٔ هوش مصنوعی",
        "version": "نسخهٔ {v}",
        "key_facts": "واقعیت‌های کلیدی",
        "disputes": "نکات مورد اختلاف",
        "coverage": "چه کسانی گزارش کردند",
        "all_reports": "همهٔ گزارش‌ها",
        "new_since": "{n} گزارش تازه پس از این خلاصه ({time})",
        "blindspot": "عمدتاً پوشش‌داده‌شده از سوی: {camp}",
        "headlines_only": "هنوز خلاصه‌ای نیست. تیترها همان‌طور که منتشر شده‌اند:",
        "extractive_note": "هنوز خلاصهٔ هوش مصنوعی نیست. جمله‌هایی که چند رسانهٔ مستقل مشترکاً "
                           "آورده‌اند، عیناً نقل‌شده:",
        "n_sources_short": "{n} منبع",
        "about": "درباره و روش کار",
        "sources": "منابع",
        "storyline": "دیگر خبرهای این رشته",
        "other_lang": "English",
        "according_to": "به گفتهٔ {x}",
        "provenance": "نوشته‌شده با {model} (پرامپت {pv}) از {n} گزارش. برچسب‌ها را کد از روی "
                      "منابع محاسبه می‌کند، نه هوش مصنوعی.",
        "source_code": "کد منبع",
        "data": "داده (JSON)",
        "copy": "رونوشت گزارشی پیشین",
        "updated": "به‌روزشده {time}",
        "empty": "هنوز خبری نیست.",
        "regions": "مناطق",
        "significance": "اهمیت",
        "ownership": "مالکیت",
        "group": "گروه استقلال",
        "lenses": "زاویه‌ها",
        "reliability": "ارجاع‌های اعتبار",
        "country": "مستقر در",
        "feeds": "فیدها",
        "rss": "آر‌اس‌اس",
        "choose_language": "زبان را انتخاب کنید",
        "not_news_agency": "حقیقت خبرگزاری نیست و خودش گزارش تولید نمی‌کند: گزارش‌های رسانه‌های "
                           "همهٔ سوها را گرد می‌آورد، بر اساس رویداد دسته‌بندی می‌کند، آنچه را "
                           "به‌طور مستقل تأیید شده از ادعای یک طرف جدا می‌کند و هر گزاره را به "
                           "منبعش پیوند می‌دهد.",
    },
}

OWNERSHIP = {
    "state": {"en": "State", "fa": "دولتی/حکومتی"},
    "public": {"en": "Public broadcaster", "fa": "رسانهٔ عمومی"},
    "private": {"en": "Private", "fa": "خصوصی"},
    "nonprofit": {"en": "Nonprofit", "fa": "غیرانتفاعی"},
    "party": {"en": "Party / faction", "fa": "حزبی/جناحی"},
    "unknown": {"en": "Unknown", "fa": "نامشخص"},
}

RELIABILITY = {
    "unreviewed": {"en": "not yet reviewed", "fa": "هنوز بررسی نشده"},
    "generally_reliable": {"en": "generally reliable", "fa": "عموماً معتبر"},
    "no_consensus": {"en": "no consensus", "fa": "بدون اجماع"},
    "generally_unreliable": {"en": "generally unreliable", "fa": "عموماً نامعتبر"},
    "deprecated": {"en": "deprecated", "fa": "منسوخ"},
    "not_listed": {"en": "not listed", "fa": "فهرست‌نشده"},
}


def t(lang: str, key: str, **kw) -> str:
    text = UI.get(lang, UI["en"]).get(key) or UI["en"][key]
    if kw:
        if lang == "fa":
            kw = {k: to_persian_digits(v) if isinstance(v, int) else v for k, v in kw.items()}
        text = text.format(**kw)
    return text


def num(lang: str, value) -> str:
    return to_persian_digits(value) if lang == "fa" else str(value)


def fmt_time(dt: datetime, lang: str, tz: str, with_date: bool = True) -> str:
    local = dt.astimezone(ZoneInfo(tz))
    hm = local.strftime("%H:%M")
    if lang == "fa":
        jy, jm, jd = jalali(local.date())
        s = f"{jd} {MONTHS_FA[jm - 1]} {jy}، {hm}" if with_date else hm
        return to_persian_digits(s)
    return local.strftime("%d %b %Y, %H:%M") if with_date else hm
