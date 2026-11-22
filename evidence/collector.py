"""Provider-neutral evidence collector for AION.

The collector never treats search results or model summaries as verified facts.
It gathers source documents with provenance for later deterministic verification.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
from dataclasses import asdict, dataclass
from html import unescape
from urllib.error import HTTPError
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from security.redaction import redact_sensitive


MAX_URL_CHARS = 4096
MAX_SEARCH_QUERY_CHARS = 4000
MAX_SEARCH_RESULTS = 10
MAX_SEARCH_CANDIDATES = 50
MAX_REDIRECTS = 3
MAX_TIMEOUT_SECONDS = 60
HARD_MAX_CHARS = 100_000
HARD_MAX_BYTES = 4_000_000
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class EvidenceCollectorError(RuntimeError):
    pass


class _NoRedirectHandler(HTTPRedirectHandler):
    """Expose redirects to the collector so every target is validated."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class EvidenceDocument:
    url: str
    title: str
    text: str
    source_type: str
    independent_group: str
    fetched_via: str

    def to_dict(self) -> dict:
        return asdict(self)


def _domain_group(url: str) -> str:
    host = (urlparse(url).hostname or "unknown").lower()
    if host.startswith("www."):
        host = host[4:]
    # Domain separation is only a candidate for independence. Ownership/origin
    # must be checked later before it can count as independent evidence.
    return f"unverified:domain:{host}"


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    raw = unescape(raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _title(raw: str, fallback: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if not match:
        return fallback
    return re.sub(r"\s+", " ", unescape(match.group(1))).strip() or fallback


def _assert_public_http_url(url: str) -> None:
    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS:
        raise EvidenceCollectorError("evidence_url_invalid")
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise EvidenceCollectorError("evidence_url_invalid")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise EvidenceCollectorError("evidence_url_invalid") from None
    if port != (443 if parsed.scheme == "https" else 80):
        raise EvidenceCollectorError("evidence_port_blocked")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except OSError:
        raise EvidenceCollectorError("evidence_host_unresolvable") from None
    parsed_addresses = 0
    for address in addresses:
        raw_ip = address[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        parsed_addresses += 1
        if not ip.is_global:
            raise EvidenceCollectorError("evidence_network_target_blocked")
    if parsed_addresses == 0:
        raise EvidenceCollectorError("evidence_host_unresolvable")


class EvidenceCollector:
    def __init__(
        self,
        timeout: int = 20,
        max_chars: int = 12000,
        max_bytes: int = 2_000_000,
        max_redirects: int = MAX_REDIRECTS,
    ) -> None:
        self.timeout = min(MAX_TIMEOUT_SECONDS, max(1, int(timeout)))
        self.max_chars = min(HARD_MAX_CHARS, max(1000, int(max_chars)))
        self.max_bytes = min(HARD_MAX_BYTES, max(4096, int(max_bytes)))
        self.max_redirects = min(MAX_REDIRECTS, max(0, int(max_redirects)))
        self.user_agent = "AION-EvidenceCollector/0.2"
        self._opener = build_opener(_NoRedirectHandler())

    def _read_public_url(self, url: str, failure_code: str) -> tuple[str, str, bytes]:
        current_url = url
        seen: set[str] = set()
        redirects = 0
        while True:
            _assert_public_http_url(current_url)
            if current_url in seen:
                raise EvidenceCollectorError("evidence_redirect_loop")
            seen.add(current_url)
            request = Request(current_url, headers={"User-Agent": self.user_agent})
            try:
                response = self._opener.open(request, timeout=self.timeout)
            except HTTPError as exc:
                if exc.code not in _REDIRECT_STATUSES:
                    try:
                        exc.close()
                    except Exception:
                        pass
                    raise EvidenceCollectorError(failure_code) from None
                location = exc.headers.get("Location", "") if exc.headers else ""
                try:
                    exc.close()
                except Exception:
                    pass
                if not isinstance(location, str) or not location.strip():
                    raise EvidenceCollectorError("evidence_redirect_invalid")
                if redirects >= self.max_redirects:
                    raise EvidenceCollectorError("evidence_redirect_limit")
                next_url = urljoin(current_url, location.strip())
                if (
                    urlparse(current_url).scheme == "https"
                    and urlparse(next_url).scheme != "https"
                ):
                    raise EvidenceCollectorError("evidence_redirect_downgrade")
                current_url = next_url
                redirects += 1
                continue
            except Exception:
                # Provider/network exception text may contain credentials or a
                # signed URL. It must not cross this trust boundary.
                raise EvidenceCollectorError(failure_code) from None

            try:
                final_url = response.geturl() or current_url
                _assert_public_http_url(final_url)
                if final_url != current_url:
                    raise EvidenceCollectorError("evidence_uncontrolled_redirect")
                content_type = response.headers.get("Content-Type", "")
                raw_bytes = response.read(self.max_bytes + 1)
            except EvidenceCollectorError:
                raise
            except Exception:
                raise EvidenceCollectorError(failure_code) from None
            finally:
                try:
                    response.close()
                except Exception:
                    pass
            if len(raw_bytes) > self.max_bytes:
                raise EvidenceCollectorError("evidence_document_too_large")
            return final_url, content_type, raw_bytes

    def fetch_url(self, url: str) -> EvidenceDocument:
        final_url, content_type, raw_bytes = self._read_public_url(
            url, "evidence_fetch_failed"
        )
        content_type = str(content_type or "").lower()
        if "text" not in content_type and "json" not in content_type and "html" not in content_type:
            raise EvidenceCollectorError("evidence_content_type_blocked")

        raw = raw_bytes.decode("utf-8", errors="replace")
        safe_url = redact_sensitive(final_url).text
        if "json" in content_type:
            try:
                parsed = json.loads(raw)
                text = json.dumps(parsed, ensure_ascii=False)
            except Exception:
                text = raw
            title = safe_url
        elif "html" in content_type or "<html" in raw.lower():
            title = _title(raw, safe_url)
            text = _strip_html(raw)
        else:
            title = safe_url
            text = re.sub(r"\s+", " ", raw).strip()

        title = redact_sensitive(title[:1000]).text
        text = redact_sensitive(text[: self.max_chars]).text
        return EvidenceDocument(
            url=safe_url,
            title=title,
            text=text,
            source_type="web_document",
            independent_group=_domain_group(final_url),
            fetched_via="direct_url",
        )

    def search_searxng(self, query: str, limit: int = 5) -> list[str]:
        base = os.getenv("AION_SEARXNG_URL", "").strip().rstrip("/")
        if not base:
            return []
        if not isinstance(query, str) or len(query) > MAX_SEARCH_QUERY_CHARS:
            raise EvidenceCollectorError("searxng_query_invalid")
        try:
            bounded_limit = int(limit)
        except (TypeError, ValueError):
            raise EvidenceCollectorError("searxng_limit_invalid") from None
        if bounded_limit <= 0:
            return []
        bounded_limit = min(bounded_limit, MAX_SEARCH_RESULTS)
        _assert_public_http_url(base)
        if urlparse(base).query:
            raise EvidenceCollectorError("searxng_url_invalid")
        safe_query = redact_sensitive(query).text
        endpoint = f"{base}/search?q={quote_plus(safe_query)}&format=json"
        try:
            _, content_type, raw = self._read_public_url(
                endpoint, "searxng_search_failed"
            )
            if "json" not in str(content_type or "").lower():
                raise EvidenceCollectorError("searxng_content_type_blocked")
            data = json.loads(raw.decode("utf-8", errors="strict"))
            if not isinstance(data, dict) or not isinstance(data.get("results", []), list):
                raise EvidenceCollectorError("searxng_response_invalid")
        except EvidenceCollectorError:
            raise
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            raise EvidenceCollectorError("searxng_response_invalid") from None

        urls: list[str] = []
        for item in data.get("results", [])[:MAX_SEARCH_CANDIDATES]:
            if not isinstance(item, dict):
                continue
            result_url = item.get("url")
            if not isinstance(result_url, str):
                continue
            try:
                _assert_public_http_url(result_url)
            except EvidenceCollectorError:
                continue
            redacted = redact_sensitive(result_url)
            if redacted.count:
                continue
            if result_url not in urls:
                urls.append(result_url)
            if len(urls) >= bounded_limit:
                break
        return urls

    def collect(self, claim: str, seed_urls: list[str] | None = None, limit: int = 5) -> list[EvidenceDocument]:
        try:
            bounded_limit = min(MAX_SEARCH_RESULTS, max(0, int(limit)))
        except (TypeError, ValueError):
            raise EvidenceCollectorError("evidence_limit_invalid") from None
        if bounded_limit == 0:
            return []
        urls: list[str] = []
        if seed_urls:
            urls.extend(seed_urls[:MAX_SEARCH_CANDIDATES])
        if len(urls) < bounded_limit:
            urls.extend(self.search_searxng(claim, limit=bounded_limit))

        seen_hashes: set[str] = set()
        documents: list[EvidenceDocument] = []
        for url in urls:
            if len(documents) >= bounded_limit:
                break
            try:
                doc = self.fetch_url(url)
            except EvidenceCollectorError:
                continue
            digest = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            documents.append(doc)
        return documents
