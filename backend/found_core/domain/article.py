"""News articles as intake text: which addresses are allowed, and the article's words.

A publisher can point intake at a news article instead of pasting it. The page is fetched
once, reduced to its headline and paragraphs here, and from then on it is ordinary pasted
text: the model suggests candidates, code keeps only quotes found in the text, and a
reviewer confirms each one. No I/O here.
"""

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from found_core.domain.errors import BadRequest
from found_core.domain.intake import MAX_TEXT_CHARS

URL_MAX = 2000
# Less than this after cleaning means the page held no article we can read.
MIN_ARTICLE_CHARS = 200

# Never part of the article's own text.
_SKIPPED = frozenset(
    {"script", "style", "noscript", "template", "svg", "nav", "header", "footer", "aside", "form",
     "button", "figure", "iframe"}
)  # fmt: skip
# Each of these is one paragraph of the article.
_BLOCKS = frozenset({"p", "h1", "h2", "h3", "li", "blockquote"})
_SPACE = re.compile(r"\s+")
# Without an <article>, short blocks are menus, share buttons and section names.
_MIN_BLOCK = 25
_MIN_LIST_ITEM = 60


def check_article_url(raw: object) -> str:
    """A plain web address: http or https, a host name, the default port, no login."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > URL_MAX:
        raise BadRequest(f"url is required, at most {URL_MAX} characters.")
    url = raw.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BadRequest("url must be an http or https address.")
    if parts.username or parts.password:
        raise BadRequest("url must not hold a user name or password.")
    try:
        port = parts.port
    except ValueError:
        raise BadRequest("url has an invalid port.") from None
    if port not in (None, 80, 443):
        raise BadRequest("url must use the default port.")
    return url


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._skip = 0
        self._article = 0
        self._block: list[str] | None = None
        self._tag = ""
        # (tag, inside <article>, text) for every paragraph, in page order.
        self.blocks: list[tuple[str, bool, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "article":
            self._article += 1
        elif tag in _BLOCKS and not self._skip:
            self._close_block()
            self._block = []
            self._tag = tag
        elif tag == "br" and self._block is not None:
            self._block.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "article":
            self._close_block()
            self._article = max(0, self._article - 1)
        elif tag in _BLOCKS:
            self._close_block()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._block is not None and not self._skip:
            self._block.append(data)

    def _close_block(self) -> None:
        if self._block is None:
            return
        text = _SPACE.sub(" ", "".join(self._block)).strip()
        if text:
            self.blocks.append((self._tag, self._article > 0, text))
        self._block = None

    def close(self) -> None:
        super().close()
        self._close_block()


def article_text(html: str, url: str) -> str:
    """The headline and paragraphs of a page as plain text, ending with where it came from.

    Paragraphs inside <article> win when the page marks one; otherwise short blocks, which
    are menus and buttons, are dropped. Scripts, forms and footers never count. The result
    is capped to what intake accepts.
    """
    parser = _ArticleParser()
    parser.feed(html)
    parser.close()
    inside = [text for _, in_article, text in parser.blocks if in_article]
    paragraphs = inside or [
        text
        for tag, _, text in parser.blocks
        if len(text) >= (_MIN_LIST_ITEM if tag == "li" else _MIN_BLOCK)
    ]
    title = _SPACE.sub(" ", parser.title).strip()
    # The headline usually repeats the page title; keep it once.
    seen: set[str] = {title}
    body: list[str] = []
    for text in paragraphs:
        if text not in seen:
            seen.add(text)
            body.append(text)
    footer = f"Source: {url}"
    room = MAX_TEXT_CHARS - len(title) - len(footer) - 4
    text = "\n\n".join(body)[:max(room, 0)].strip()
    return "\n\n".join(part for part in (title, text, footer) if part)


def has_article(text: str, url: str) -> bool:
    """Enough words beyond the headline and source line to be worth reading."""
    return len(text) - len(f"Source: {url}") >= MIN_ARTICLE_CHARS
