"""Fetching a URL, with the paranoia a local-first agent needs.

The interesting problem is not HTTP. It is that ``http://127.0.0.1:8080`` and
``http://169.254.169.254/`` are valid URLs a model can produce, and a tool that fetches
them turns "summarise this page" into a way to read the machine's metadata service, an
admin panel on loopback, or anything else the user's network exposes. So:

* only ``http`` and ``https``;
* no credentials embedded in the URL;
* the host is **resolved** and every address is checked against loopback, private,
  link-local, reserved, multicast and unspecified ranges - before the request and again
  after each redirect, because a redirect is just a URL someone else chose for you;
* redirects are followed manually, with a hop limit, so the check cannot be skipped;
* there is a byte limit, a timeout, and a content-type allowlist, because a 4 GiB binary
  is not a document;
* the response is hashed, so an excerpt can be tied to exactly what was read.

Private addresses can be allowed deliberately (``tools.fetch_allow_private_hosts``) - the
tests and the acceptance script need a local server, and a user running Ollama on
``127.0.0.1`` may want the same - but the default is to refuse, and the refusal says why.
"""

from __future__ import annotations

import hashlib
import html as html_module
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Mapping

from archx_agent.helpers.exceptions import ToolError

ALLOWED_SCHEMES = ("http", "https")
TEXT_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xhtml+xml",
    "application/xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/ld+json",
)
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
DEFAULT_TIMEOUT = 15
DEFAULT_MAX_BYTES = 1_000_000
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_USER_AGENT = "archx-agent/0.28 (+local research)"


class FetchBlockedError(ToolError):
    """The request was refused by policy, not by the network."""


class FetchFailedError(ToolError):
    """The request was attempted and failed."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Make urllib hand 3xx responses back to us instead of following them.

    Following is not optional to supervise: a redirect target is chosen by the remote
    server, so it must go through the same address checks as the original URL.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect)


class _TextExtractor(HTMLParser):
    """A tiny HTML-to-text converter.

    It is not a renderer and does not try to be: scripts, styles and comments are dropped,
    block-level tags become newlines, and entities are decoded. That is enough to quote a
    page honestly, and small enough to read.
    """

    SKIP = {"script", "style", "noscript", "template", "svg"}
    BLOCK = {
        "p", "div", "section", "article", "header", "footer", "li", "tr", "td", "th",
        "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "table",
        "ul", "ol", "dd", "dt", "figure", "figcaption", "main", "aside", "nav",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self.title: str = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001 - stdlib signature
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
            return
        self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def html_to_text(markup: str) -> tuple[str, str]:
    """Return ``(text, title)`` for an HTML document."""
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # noqa: BLE001 - a broken page is still text
        return re.sub(r"<[^>]+>", " ", markup), ""
    title = " ".join(parser.title.split())
    if not title:
        match = re.search(r"(?is)<title[^>]*>(.*?)</title>", markup)
        if match:
            title = html_module.unescape(" ".join(match.group(1).split()))
    return parser.text(), title


def _addresses(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchFailedError(f"cannot resolve {host!r}: {exc}") from exc
    found: list[str] = []
    for info in infos:
        address = info[4][0]
        if address not in found:
            found.append(address)
    return found


def _is_private(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:  # pragma: no cover - getaddrinfo returns valid IPs
        return True
    return bool(
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_reserved
        or parsed.is_multicast
        or parsed.is_unspecified
    )


def check_url(url: str, *, allow_private_hosts: bool = False) -> urllib.parse.ParseResult:
    """Validate a URL and its resolved addresses. Raises :class:`FetchBlockedError`."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise FetchBlockedError(
            f"{parsed.scheme or 'that'} URLs are not fetched (only http and https)"
        )
    if parsed.username or parsed.password:
        raise FetchBlockedError("credentials in a URL are refused; use a secret reference")
    host = parsed.hostname
    if not host:
        raise FetchBlockedError(f"{url!r} has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = _addresses(host, port)
    if not allow_private_hosts:
        for address in addresses:
            if _is_private(address):
                raise FetchBlockedError(
                    f"{host} resolves to {address}, which is a private or local address; "
                    "set tools.fetch_allow_private_hosts=true to allow it deliberately"
                )
    return parsed


def _decode(body: bytes, charset: str | None) -> str:
    for candidate in (charset, "utf-8", "latin-1"):
        if not candidate:
            continue
        try:
            return body.decode(candidate, errors="replace")
        except LookupError:
            continue
    return body.decode("utf-8", errors="replace")


def fetch_url(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    allow_private_hosts: bool = False,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Any]:
    """Fetch a text document. Returns a dict; never returns binary content.

    The result is deliberately plain data (no response object), because it is stored,
    traced and quoted - an object with a live socket in it would be none of those.
    """
    if max_bytes < 1:
        raise FetchBlockedError("max_bytes must be positive")
    current = str(url or "").strip()
    hops: list[str] = []
    for _hop in range(int(max_redirects) + 1):
        check_url(current, allow_private_hosts=allow_private_hosts)
        request = urllib.request.Request(
            current,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
                "Accept-Language": "en",
            },
        )
        try:
            with _opener().open(request, timeout=float(timeout)) as response:
                status = int(getattr(response, "status", 200) or 200)
                headers = {key.lower(): value for key, value in response.headers.items()}
                body = response.read(int(max_bytes) + 1)
                final = response.geturl()
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else None
            if exc.code in REDIRECT_STATUSES and location:
                if len(hops) >= int(max_redirects):
                    raise FetchBlockedError(
                        f"too many redirects (limit {max_redirects}); last was {current}"
                    ) from exc
                hops.append(current)
                current = urllib.parse.urljoin(current, location)
                continue
            raise FetchFailedError(f"HTTP {exc.code} from {current}") from exc
        except urllib.error.URLError as exc:
            raise FetchFailedError(f"cannot reach {current}: {exc.reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise FetchFailedError(f"{current} timed out after {timeout}s") from exc

        truncated = len(body) > int(max_bytes)
        body = body[: int(max_bytes)]
        content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
        charset = None
        if "charset=" in (headers.get("content-type") or "").lower():
            charset = (headers.get("content-type") or "").split("charset=")[-1].split(";")[0].strip(" \"'")
        if content_type and not any(content_type.startswith(ok) for ok in TEXT_CONTENT_TYPES):
            raise FetchBlockedError(
                f"{current} returned {content_type!r}, which is not a text document"
            )
        text = _decode(body, charset)
        title = ""
        if "html" in content_type or text.lstrip()[:1] == "<":
            text, title = html_to_text(text)
        return {
            "url": url,
            "final_url": final,
            "status": status,
            "content_type": content_type or "text/plain",
            "charset": charset,
            "bytes": len(body),
            "truncated": truncated,
            "sha256": hashlib.sha256(body).hexdigest(),
            "title": title,
            "text": text,
            "redirects": hops,
        }
    raise FetchBlockedError(f"too many redirects (limit {max_redirects})")


def fetch_limits(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The limits a call would use, for `archx-agent tools limits` style output."""

    def _get(key: str, default: Any) -> Any:
        if config is None:
            return default
        try:
            return config.get(key)
        except Exception:  # noqa: BLE001
            return default

    return {
        "timeout_seconds": int(_get("tools.fetch_timeout_seconds", DEFAULT_TIMEOUT)),
        "max_bytes": int(_get("tools.fetch_max_bytes", DEFAULT_MAX_BYTES)),
        "max_redirects": int(_get("tools.fetch_max_redirects", DEFAULT_MAX_REDIRECTS)),
        "allow_private_hosts": bool(_get("tools.fetch_allow_private_hosts", False)),
    }


__all__ = [
    "ALLOWED_SCHEMES",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_TIMEOUT",
    "FetchBlockedError",
    "FetchFailedError",
    "check_url",
    "fetch_limits",
    "fetch_url",
    "html_to_text",
]
