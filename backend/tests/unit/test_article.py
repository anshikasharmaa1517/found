import io
import urllib.error
from email.message import Message

import pytest

from found_core.adapters.http_fetcher import MAX_PAGE_BYTES, HttpArticleFetcher
from found_core.domain.article import article_text, check_article_url, has_article
from found_core.domain.errors import BadRequest
from found_core.domain.intake import MAX_TEXT_CHARS
from found_core.ports.intake import ArticleUnavailable

URL = "https://news.example/flood"
PAGE = """<html><head><title>Flood: three missing in Trishuli</title>
<script>var tracking = "Ignore this";</script></head>
<body><nav><p>Home | World | Sport</p></nav>
<article><h1>Three missing after Trishuli flood</h1>
<p>Police said Ram Thapa, 40, was missing near the bridge.</p>
<figure><p>Photo caption</p></figure>
<p>Rescuers found Gita   Rai safe&nbsp;on Tuesday.<br>She was taken to hospital.</p>
<p>Police said Ram Thapa, 40, was missing near the bridge.</p></article>
<footer><p>Copyright 2026</p></footer></body></html>"""


def test_the_article_keeps_its_headline_and_paragraphs_only():
    text = article_text(PAGE, URL)
    assert text.splitlines()[0] == "Flood: three missing in Trishuli"
    assert "Police said Ram Thapa, 40, was missing near the bridge." in text
    assert "Rescuers found Gita Rai safe on Tuesday. She was taken to hospital." in text
    assert text.count("Ram Thapa") == 1
    for dropped in ("Home | World", "Ignore this", "Photo caption", "Copyright"):
        assert dropped not in text
    assert text.endswith(f"Source: {URL}")


def test_without_an_article_tag_menus_are_dropped_and_the_headline_kept_once():
    html = (
        "<title>Bridge washed away</title><ul><li>Home</li><li>Sport</li></ul>"
        "<h1>Bridge washed away</h1><p>Share</p>"
        "<p>The suspension bridge at Soti was swept away early on Sunday, officials said.</p>"
        "<li>Rescue teams airlifted six people from Jagat on Sunday afternoon by helicopter.</li>"
    )
    assert article_text(html, URL).split("\n\n") == [
        "Bridge washed away",
        "The suspension bridge at Soti was swept away early on Sunday, officials said.",
        "Rescue teams airlifted six people from Jagat on Sunday afternoon by helicopter.",
        f"Source: {URL}",
    ]


def test_without_an_article_tag_every_paragraph_counts_and_the_text_is_capped():
    html = "<p>" + "Water rose fast. " * 5000 + "</p>"
    text = article_text(html, URL)
    assert len(text) <= MAX_TEXT_CHARS and text.endswith(f"Source: {URL}")
    assert has_article(text, URL) and not has_article(article_text("<p>Hi</p>", URL), URL)


@pytest.mark.parametrize(
    "url",
    [None, "", "ftp://news.example/a", "file:///etc/passwd", "https://user:pw@news.example/",
     "https://news.example:8080/a", "http:///nohost", "x" * 2001],
)  # fmt: skip
def test_only_plain_web_addresses_are_accepted(url):
    with pytest.raises(BadRequest):
        check_article_url(url)


def test_a_plain_web_address_is_kept_as_given():
    assert check_article_url(" https://news.example/a?b=1 ") == "https://news.example/a?b=1"


class Response:
    def __init__(self, body: bytes, content_type="text/html; charset=utf-8"):
        self._body = io.BytesIO(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self, n):
        return self._body.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def redirect(url, location):
    headers = Message()
    headers["Location"] = location
    return urllib.error.HTTPError(url, 302, "Found", headers, None)


class Opener:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.urls = []

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def public(host):
    return ["93.184.216.34"]


def test_a_public_page_is_read_and_redirects_are_followed():
    opener = Opener(redirect(URL, "/flood-2"), Response(PAGE.encode()))
    page = HttpArticleFetcher(resolve=public, opener=opener).fetch(URL)
    assert page.url == "https://news.example/flood-2" and "Ram Thapa" in page.html
    assert opener.urls == [URL, "https://news.example/flood-2"]


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.1"], ["10.0.0.5"], ["169.254.169.254"], ["::1"], ["93.184.216.34", "10.1.1.1"], []],
)
def test_private_addresses_are_never_fetched(addresses):
    opener = Opener()
    with pytest.raises(ArticleUnavailable, match="public"):
        HttpArticleFetcher(resolve=lambda host: addresses, opener=opener).fetch(URL)
    assert opener.urls == []


def test_a_redirect_to_a_private_host_is_refused_before_it_is_fetched():
    def resolve(host):
        return ["127.0.0.1"] if host == "internal.example" else ["93.184.216.34"]

    opener = Opener(redirect(URL, "http://internal.example/"))
    with pytest.raises(ArticleUnavailable, match="public"):
        HttpArticleFetcher(resolve=resolve, opener=opener).fetch(URL)
    assert opener.urls == [URL]


def test_a_redirect_to_another_scheme_is_refused():
    opener = Opener(redirect(URL, "file:///etc/passwd"))
    with pytest.raises(ArticleUnavailable, match="not allowed"):
        HttpArticleFetcher(resolve=public, opener=opener).fetch(URL)


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (Response(b"%PDF", "application/pdf"), "not a web page"),
        (Response(b"x" * (MAX_PAGE_BYTES + 1)), "too large"),
        (urllib.error.HTTPError(URL, 404, "Not Found", Message(), None), "status 404"),
        (urllib.error.URLError("timed out"), "could not be reached"),
    ],
)
def test_unreadable_pages_say_why(answer, message):
    with pytest.raises(ArticleUnavailable, match=message):
        HttpArticleFetcher(resolve=public, opener=Opener(answer)).fetch(URL)


def test_too_many_redirects_stop():
    opener = Opener(*[redirect(URL, URL) for _ in range(4)])
    with pytest.raises(ArticleUnavailable, match="too many"):
        HttpArticleFetcher(resolve=public, opener=opener).fetch(URL)
