import socket
from urllib.error import HTTPError
from unittest.mock import patch

from evidence.collector import (
    EvidenceCollector,
    EvidenceCollectorError,
    EvidenceDocument,
)


class FakeCollector(EvidenceCollector):
    def search_searxng(self, query: str, limit: int = 5):
        return [
            "https://source-a.example/doc",
            "https://source-b.example/doc",
            "https://copy.example/doc",
        ]

    def fetch_url(self, url: str):
        if "source-a" in url:
            text = "Independent evidence A"
        elif "source-b" in url:
            text = "Independent evidence B"
        else:
            text = "Independent evidence A"  # duplicate content
        return EvidenceDocument(
            url=url,
            title=url,
            text=text,
            source_type="web_document",
            independent_group=url.split("/")[2],
            fetched_via="test",
        )


collector = FakeCollector()
docs = collector.collect("test claim", limit=5)
assert len(docs) == 2
assert len({doc.independent_group for doc in docs}) == 2
assert all(doc.source_type == "web_document" for doc in docs)

collector_no_search = EvidenceCollector()
assert collector_no_search.search_searxng("anything") == []


class FakeResponse:
    def __init__(self, url, body=b"safe evidence", content_type="text/plain"):
        self._url = url
        self._body = body
        self.headers = {"Content-Type": content_type}

    def geturl(self):
        return self._url

    def read(self, amount):
        return self._body[:amount]

    def close(self):
        pass


class QueueOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request.full_url)
        outcome = self.responses.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


public_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def guarded_dns(host, port, **kwargs):
    if host == "127.0.0.1":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
    return public_dns

# Redirects are handled manually. A redirect to loopback is rejected before a
# second connection, and the target URL is not exposed in the error text.
redirect = HTTPError(
    "https://public.example/start",
    302,
    "Found",
    {"Location": "https://127.0.0.1/private?api_key=TOPSECRET12345678"},
    None,
)
guarded = EvidenceCollector()
guarded._opener = QueueOpener([redirect])
with patch("evidence.collector.socket.getaddrinfo", side_effect=guarded_dns):
    try:
        guarded.fetch_url("https://public.example/start")
    except EvidenceCollectorError as exc:
        assert str(exc) == "evidence_network_target_blocked", str(exc)
        assert "127.0.0.1" not in str(exc) and "TOPSECRET" not in str(exc)
    else:
        raise AssertionError("Redirect to a private target must be blocked")
assert guarded._opener.calls == ["https://public.example/start"]

# A bounded public redirect is accepted and final provenance is preserved.
public_redirect = HTTPError(
    "https://public.example/start",
    302,
    "Found",
    {"Location": "https://second.example/final"},
    None,
)
redirected = EvidenceCollector()
redirected._opener = QueueOpener([
    public_redirect,
    FakeResponse("https://second.example/final", b"independent result"),
])
with patch("evidence.collector.socket.getaddrinfo", return_value=public_dns):
    redirected_doc = redirected.fetch_url("https://public.example/start")
assert redirected_doc.url == "https://second.example/final"
assert redirected_doc.independent_group == "unverified:domain:second.example"

downgrade = HTTPError(
    "https://public.example/start",
    302,
    "Found",
    {"Location": "http://second.example/final"},
    None,
)
downgrade_guard = EvidenceCollector()
downgrade_guard._opener = QueueOpener([downgrade])
with patch("evidence.collector.socket.getaddrinfo", return_value=public_dns):
    try:
        downgrade_guard.fetch_url("https://public.example/start")
    except EvidenceCollectorError as exc:
        assert str(exc) == "evidence_redirect_downgrade", str(exc)
    else:
        raise AssertionError("HTTPS downgrade redirect must be blocked")

# Raw exception text and common credentials in a fetched document never cross
# the collector boundary.
secret = "sk-proj-" + ("A" * 32)
failed = EvidenceCollector()
failed._opener = QueueOpener([RuntimeError(f"network failure {secret}")])
with patch("evidence.collector.socket.getaddrinfo", return_value=public_dns):
    try:
        failed.fetch_url("https://public.example/fail")
    except EvidenceCollectorError as exc:
        assert str(exc) == "evidence_fetch_failed"
        assert secret not in str(exc)
    else:
        raise AssertionError("Network error must fail closed")

redacting = EvidenceCollector()
redacting._opener = QueueOpener([
    FakeResponse("https://public.example/doc", f"text {secret}".encode()),
])
with patch("evidence.collector.socket.getaddrinfo", return_value=public_dns):
    safe_doc = redacting.fetch_url("https://public.example/doc")
assert secret not in safe_doc.text and "[REDACTED_SECRET]" in safe_doc.text

# The configured search endpoint is subject to the same public-network guard.
with patch.dict("os.environ", {"AION_SEARXNG_URL": "http://127.0.0.1:8080"}):
    try:
        EvidenceCollector().search_searxng("claim")
    except EvidenceCollectorError as exc:
        assert str(exc) in {"evidence_port_blocked", "evidence_network_target_blocked"}
    else:
        raise AssertionError("Private SearXNG endpoint must be blocked by default")

search_secret = "sk-proj-" + ("B" * 32)
safe_endpoint = (
    "https://search.example/search?q=claim+%5BREDACTED_SECRET%5D&format=json"
)
searcher = EvidenceCollector()
searcher._opener = QueueOpener([
    FakeResponse(
        safe_endpoint,
        b'{"results":[{"url":"https://source.example/doc"},'
        b'{"url":"http://127.0.0.1/private"}]}',
        "application/json",
    )
])
with patch.dict("os.environ", {"AION_SEARXNG_URL": "https://search.example"}), patch(
    "evidence.collector.socket.getaddrinfo", side_effect=guarded_dns
):
    found = searcher.search_searxng(f"claim {search_secret}")
assert found == ["https://source.example/doc"]
assert search_secret not in searcher._opener.calls[0]

# Constructor values are capped even when an untrusted caller requests
# effectively unbounded network and response limits.
bounded = EvidenceCollector(timeout=9999, max_chars=999_999_999, max_bytes=999_999_999)
assert bounded.timeout == 60
assert bounded.max_chars == 100_000
assert bounded.max_bytes == 4_000_000

print("EVIDENCE COLLECTOR TEST: PASS")
