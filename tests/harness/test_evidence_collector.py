from evidence.collector import EvidenceCollector, EvidenceDocument


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

print("EVIDENCE COLLECTOR TEST: PASS")
