"""Provider-neutral evidence collector for AION.

The collector never treats search results or model summaries as verified facts.
It gathers source documents with provenance for later deterministic verification.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from html import unescape
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen


class EvidenceCollectorError(RuntimeError):
    pass


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
    return host


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


class EvidenceCollector:
    def __init__(self, timeout: int = 20, max_chars: int = 12000) -> None:
        self.timeout = timeout
        self.max_chars = max_chars
        self.user_agent = "AION-EvidenceCollector/0.1"

    def fetch_url(self, url: str) -> EvidenceDocument:
        if not url.startswith(("http://", "https://")):
            raise EvidenceCollectorError("Only http/https URLs are supported")
        request = Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                raw_bytes = response.read()
        except Exception as exc:
            raise EvidenceCollectorError(f"Fetch failed for {url}: {exc}") from exc

        if "text" not in content_type and "json" not in content_type and "html" not in content_type:
            raise EvidenceCollectorError(f"Unsupported content type: {content_type}")

        raw = raw_bytes.decode("utf-8", errors="replace")
        if "json" in content_type:
            try:
                parsed = json.loads(raw)
                text = json.dumps(parsed, ensure_ascii=False)
            except Exception:
                text = raw
            title = url
        elif "html" in content_type or "<html" in raw.lower():
            title = _title(raw, url)
            text = _strip_html(raw)
        else:
            title = url
            text = re.sub(r"\s+", " ", raw).strip()

        text = text[: self.max_chars]
        return EvidenceDocument(
            url=url,
            title=title,
            text=text,
            source_type="web_document",
            independent_group=_domain_group(url),
            fetched_via="direct_url",
        )

    def search_searxng(self, query: str, limit: int = 5) -> list[str]:
        base = os.getenv("AION_SEARXNG_URL", "").strip().rstrip("/")
        if not base:
            return []
        endpoint = f"{base}/search?q={quote_plus(query)}&format=json"
        request = Request(endpoint, headers={"User-Agent": self.user_agent})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            raise EvidenceCollectorError(f"SearXNG search failed: {exc}") from exc

        urls: list[str] = []
        for item in data.get("results", []):
            url = item.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                urls.append(url)
            if len(urls) >= limit:
                break
        return urls

    def collect(self, claim: str, seed_urls: list[str] | None = None, limit: int = 5) -> list[EvidenceDocument]:
        urls: list[str] = []
        if seed_urls:
            urls.extend(seed_urls)
        if len(urls) < limit:
            urls.extend(self.search_searxng(claim, limit=limit))

        seen_hashes: set[str] = set()
        documents: list[EvidenceDocument] = []
        for url in urls:
            if len(documents) >= limit:
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
