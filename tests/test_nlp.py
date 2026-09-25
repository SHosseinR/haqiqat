from collections import Counter
from datetime import date
from pathlib import Path

from haqiqat.ingest import canonical_url, extract_text
from haqiqat.jalali import jalali
from haqiqat.nlp import dedup
from haqiqat.nlp.geo import Gazetteer, story_countries
from haqiqat.nlp.lang import detect
from haqiqat.nlp.normalize import normalize, sentences, to_persian_digits, tokens

REPO = Path(__file__).resolve().parent.parent


def test_normalize_unifies_arabic_and_persian_letters_and_digits():
    assert normalize("كيك ۱۲۳ ٤٥") == "کیک 123 45"
    assert normalize("اسرائيل") == normalize("اسراییل")


def test_tokens_keep_zwnj_words_whole():
    assert tokens("می‌گویند مقام‌ها") == ["می‌گویند", "مقام‌ها"]
    assert tokens("Drone attack, Isfahan!") == ["drone", "attack", "isfahan"]


def test_sentences_split_on_persian_question_mark():
    assert sentences("چه شد؟ هیچ. Done!") == ["چه شد؟", "هیچ.", "Done!"]


def test_language_detection():
    assert detect("Several drones attacked a site in Isfahan, officials said.") == "en"
    assert detect("مقام‌های ایران می‌گویند حمله پهپادی به اصفهان ناکام ماند") == "fa"
    assert detect("قالت وزارة الخارجية إن الهجوم كان محدودا في المدينة") == "ar"
    assert detect("short", default="fa") == "fa"


def test_minhash_near_duplicates():
    a = "The foreign ministry said on Monday that talks in Vienna would resume next week " * 3
    b = a.replace("Monday", "Tuesday")
    c = "An earthquake struck eastern Turkey, killing at least twelve people, officials said " * 3
    sa, sb, sc = dedup.signature(a), dedup.signature(b), dedup.signature(c)
    assert dedup.similarity(sa, sb) > 0.6
    assert dedup.similarity(sa, sc) < 0.2


def test_gazetteer_bilingual():
    gaz = Gazetteer.load(REPO / "config" / "gazetteer.yaml")
    assert set(gaz.countries("Drone attack hits Isfahan, Iran")) == {"IR"}
    assert set(gaz.countries("حمله پهپادی به اصفهان")) == {"IR"}
    assert set(gaz.countries("talks in Vienna between Iran and the United States")) == {
        "AT", "IR", "US"}
    # "us" the pronoun is not the United States
    assert "US" not in gaz.countries("they told us nothing")
    assert gaz.display("IR", "fa") == "ایران"


def test_story_countries_needs_share_of_articles():
    per_article = [Counter({"IR": 2, "US": 1}), Counter({"IR": 1}), Counter({"IR": 1})]
    assert story_countries(per_article) == ["IR", "US"]
    per_article.append(Counter({"IR": 1}))
    assert story_countries(per_article, min_share=0.5) == ["IR"]


def test_jalali_conversion():
    assert jalali(date(2024, 3, 20)) == (1403, 1, 1)
    assert jalali(date(2025, 3, 21)) == (1404, 1, 1)
    assert to_persian_digits(1404) == "۱۴۰۴"


def test_canonical_url_strips_tracking():
    assert canonical_url("HTTPS://Example.com/a?utm_source=x&id=3#frag") == \
        "https://example.com/a?id=3"


def test_extract_text_keeps_zwnj():
    s = "مقام‌های ایران می‌گویند که گفت‌وگوها ادامه دارد. " * 10
    out = extract_text(f"<html><body><article><p>{s}</p></article></body></html>")
    assert out and "\u200c" in out and "\u034f" not in out


def test_feed_links_must_be_web_urls():
    from datetime import UTC, datetime

    from haqiqat.ingest import parse_rss

    rss = (b'<?xml version="1.0"?><rss version="2.0"><channel>'
           b"<item><title>ok</title><link>https://a.test/1</link></item>"
           b"<item><title>evil</title><link>javascript:alert(1)</link></item>"
           b"</channel></rss>")
    items = parse_rss(rss, datetime.now(UTC))
    assert [i.url for i in items] == ["https://a.test/1"]
