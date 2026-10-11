"""News articles fetched over the public internet, for intake.

Only public addresses are fetched: every host, including each redirect's, must resolve to
global IP addresses, so a link can never reach the Lambda runtime, a private network or a
metadata service. Pages are read once, within a short time and a size limit.
"""

import ipaddress
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

from found_core.domain.article import check_article_url
from found_core.domain.errors import BadRequest
from found_core.ports.intake import ArticleUnavailable, FetchedPage

MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 6
USER_AGENT = "Mozilla/5.0 (compatible; FoundIntake/1.0; disaster report intake)"

Resolver = Callable[[str], list[str]]


def _resolve(host: str) -> list[str]:
    try:
        return [info[4][0] for info in socket.getaddrinfo(host, None)]
    except OSError:
        raise ArticleUnavailable("That address could not be found.") from None


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Redirects are followed by hand, so each new host is checked first."""

    def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


class HttpArticleFetcher:
    def __init__(self, resolve: Resolver = _resolve, opener=None) -> None:  # type: ignore[no-untyped-def]
        self._resolve = resolve
        self._opener = opener or urllib.request.build_opener(_NoRedirects)

    def fetch(self, url: str) -> FetchedPage:
        for _ in range(MAX_REDIRECTS + 1):
            self._check_host(url)
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}
            )
            try:
                response = self._opener.open(request, timeout=TIMEOUT_SECONDS)
            except urllib.error.HTTPError as err:
                if err.code in (301, 302, 303, 307, 308) and err.headers.get("Location"):
                    url = self._next(url, err.headers["Location"])
                    continue
                raise ArticleUnavailable(f"The site answered with status {err.code}.") from None
            except (urllib.error.URLError, TimeoutError, OSError):
                raise ArticleUnavailable("The site could not be reached in time.") from None
            with response:
                return self._page(url, response)
        raise ArticleUnavailable("The address redirected too many times.")

    def _next(self, current: str, location: str) -> str:
        try:
            return check_article_url(urljoin(current, location))
        except BadRequest:
            raise ArticleUnavailable(
                "The address redirected somewhere that is not allowed."
            ) from None

    def _check_host(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        addresses = self._resolve(host)
        public = all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)
        if not addresses or not public:
            raise ArticleUnavailable("Only public web addresses can be read.")

    def _page(self, url: str, response) -> FetchedPage:  # type: ignore[no-untyped-def]
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            raise ArticleUnavailable("That address is not a web page.")
        data = response.read(MAX_PAGE_BYTES + 1)
        if len(data) > MAX_PAGE_BYTES:
            raise ArticleUnavailable("That page is too large to read.")
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            html = data.decode(charset, errors="replace")
        except LookupError:
            html = data.decode("utf-8", errors="replace")
        return FetchedPage(url=url, html=html)
