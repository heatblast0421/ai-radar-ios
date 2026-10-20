import XCTest
@testable import AIRadar

/// Decoding tests run against JSON produced by the real backend (see backend/tests/export_ios_fixtures.py)
/// plus snapshots of live production data, so app and backend can't silently drift apart.
final class DecodingTests: XCTestCase {
    private let api = APIClient()

    private func fixture(_ name: String) throws -> Data {
        let bundle = Bundle(for: DecodingTests.self)
        let url = try XCTUnwrap(bundle.url(forResource: name, withExtension: "json")
            ?? bundle.url(forResource: name, withExtension: "json", subdirectory: "Fixtures"), "missing fixture \(name)")
        return try Data(contentsOf: url)
    }

    func testFeedPage() throws {
        let page = try api.decode(FeedPage.self, from: fixture("feed_pulse_top_1"))
        XCTAssertGreaterThan(page.items.count, 3)
        let gpt = try XCTUnwrap(page.items.first { $0.title.contains("GPT-7") })
        XCTAssertEqual(gpt.source.id, "openai-news")
        XCTAssertEqual(gpt.importance, "high")
        XCTAssertEqual(gpt.metrics?.hnPoints, 150)
        XCTAssertTrue(gpt.isAISummary)
        XCTAssertNotNil(gpt.publishedDate)
        XCTAssertFalse(gpt.supporting?.isEmpty ?? true)
    }

    func testRealFeedPageDecodes() throws {
        let page = try api.decode(FeedPage.self, from: fixture("real_feed_pulse"))
        XCTAssertEqual(page.items.count, 30)
        XCTAssertTrue(page.items.allSatisfy { !$0.title.isEmpty && !$0.url.isEmpty })
    }

    func testItemDetailWithExplanation() throws {
        let detail = try api.decode(ItemDetail.self, from: fixture("item_detail"))
        XCTAssertTrue(detail.card.title.contains("GPT-7"))
        XCTAssertFalse((detail.extras.sourceText ?? "").isEmpty)
        let expl = try XCTUnwrap(detail.extras.explanation)
        XCTAssertNotNil(expl.quick?["summary"]?.text)
        XCTAssertEqual(expl.deep?["evidence"]?["evidence_given"]?.text, "None stated")
        XCTAssertEqual(expl.deep?["strengths"]?.list, ["Tool calling"])
        XCTAssertEqual(expl.deep?["glossary"]?.terms.first?.term, "tool calling")
        XCTAssertEqual(expl.deep?["explore"]?["experiments"]?.list.count, 1)
        XCTAssertTrue(expl.quickMeta?.warnings?.contains("99%") ?? false, "invented numbers are flagged")
    }

    func testRealItemDetailDecodes() throws {
        let detail = try api.decode(ItemDetail.self, from: fixture("real_item_detail"))
        XCTAssertFalse(detail.card.title.isEmpty)
    }

    func testRepoDetail() throws {
        let repo = try api.decode(RepoDetail.self, from: fixture("repo_detail"))
        XCTAssertEqual(repo.card.fullName, "acme/agent-harness")
        XCTAssertEqual(repo.card.growth?.trendAvailable, false)
        XCTAssertNil(repo.card.growth?.starsWeek, "growth must never be fabricated")
        XCTAssertEqual(repo.card.growth?.avgStarsPerDaySinceCreation, 120)
        XCTAssertEqual(repo.extras.snapshots?.count, 1)
        XCTAssertEqual(repo.card.spottedOn?.compactMap(\.label).sorted(), ["GitHub Trending", "Trendshift"])
    }

    func testRealRepoDataDecodes() throws {
        let page = try api.decode(RepoPage.self, from: fixture("real_github_emerging"))
        XCTAssertFalse(page.items.isEmpty)
        let detail = try api.decode(RepoDetail.self, from: fixture("real_repo_detail"))
        XCTAssertGreaterThan(detail.card.stars, 0)
    }

    func testMetaBriefingSearch() throws {
        let meta = try api.decode(Meta.self, from: fixture("meta"))
        XCTAssertEqual(meta.apiVersion, 1)
        XCTAssertTrue(meta.topics.contains { $0.id == "agents" })
        XCTAssertTrue(meta.llm?.configured ?? false)
        let real = try api.decode(Meta.self, from: fixture("real_meta"))
        XCTAssertGreaterThan(real.sources.count, 20)

        let briefing = try api.decode(Briefing.self, from: fixture("briefing"))
        XCTAssertTrue(briefing.available)
        XCTAssertFalse(briefing.bullets?.isEmpty ?? true)
        XCTAssertFalse(briefing.items?.isEmpty ?? true)

        let index = try api.decode(SearchIndex.self, from: fixture("search"))
        XCTAssertTrue(index.entries.contains { $0.isRepo })
    }
}

final class JSONValueTests: XCTestCase {
    func testTolerantShapes() throws {
        let json = """
        {"a": "text", "b": ["x", "y"], "c": 3, "d": {"term": "RAG", "meaning": "retrieval"}, "e": null,
         "glossary": [{"term": "MCP", "meaning": "protocol"}, "plain"]}
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let v = try decoder.decode(JSONValue.self, from: Data(json.utf8))
        XCTAssertEqual(v["a"]?.text, "text")
        XCTAssertEqual(v["a"]?.list, ["text"])
        XCTAssertEqual(v["b"]?.list, ["x", "y"])
        XCTAssertEqual(v["c"]?.text, "3")
        XCTAssertNil(v["e"]?.text)
        XCTAssertEqual(v["glossary"]?.terms.map(\.term), ["MCP", "plain"])
    }

    func testSnakeAndCamelLookup() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let v = try decoder.decode(JSONValue.self, from: Data(#"{"why_it_matters": "because"}"#.utf8))
        XCTAssertEqual(v["why_it_matters"]?.text, "because")
        XCTAssertEqual(v["whyItMatters"]?.text, "because")
    }
}

@MainActor
final class StoreTests: XCTestCase {
    func testBookmarksPersistAcrossInstances() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("bm-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        let store = BookmarkStore(fileURL: url)
        let entry = SavedEntry(id: "abc", kind: .item, itemKind: "paper", title: "A paper", summary: "s",
                               url: "https://arxiv.org/abs/1", source: "arXiv", topics: ["rag"], savedAt: Date())
        store.toggle(entry)
        XCTAssertTrue(store.isSaved("abc"))
        let reopened = BookmarkStore(fileURL: url)
        XCTAssertTrue(reopened.isSaved("abc"), "bookmarks survive an app restart")
        XCTAssertEqual(reopened.topicAffinity["rag"], 1)
        reopened.toggle(entry)
        XCTAssertFalse(BookmarkStore(fileURL: url).isSaved("abc"))
    }

    func testPreferencesPersist() {
        let suite = "test-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let prefs = Preferences(defaults: defaults)
        XCTAssertEqual(prefs.followedTopics, Preferences.defaultTopics)
        prefs.toggle(topic: "agents")
        prefs.appearance = .light
        let again = Preferences(defaults: defaults)
        XCTAssertFalse(again.followedTopics.contains("agents"))
        XCTAssertEqual(again.appearance, .light)
    }
}

final class RankingTests: XCTestCase {
    private func card(_ id: String, score: Double, topics: [String], importance: String? = nil) throws -> FeedCard {
        var object: [String: Any] = [
            "id": id, "kind": "article", "title": "T \(id)", "summary": "", "summary_kind": "source",
            "url": "https://x/\(id)", "source": ["id": "s", "name": "S"], "topics": topics, "score": score,
            "discovered_at": "2020-01-01T00:00:00Z",
        ]
        if let importance { object["importance"] = importance }
        let data = try JSONSerialization.data(withJSONObject: object)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(FeedCard.self, from: data)
    }

    func testForYouBoostsFollowedTopics() throws {
        let a = try card("a", score: 60, topics: ["industry"])
        let b = try card("b", score: 55, topics: ["agents"])
        let ranked = PersonalRanker.rank([a, b], followed: ["agents"], affinity: [:])
        XCTAssertEqual(ranked.map(\.card.id), ["b", "a"])
        XCTAssertEqual(ranked.first?.matchedTopics, ["agents"])
        // With no followed topics the server order is kept.
        XCTAssertEqual(PersonalRanker.rank([a, b], followed: [], affinity: [:]).map(\.card.id), ["a", "b"])
    }

    func testBreakingAlertsNeedBaselineAndAreNotRepeated() throws {
        let suite = "alerts-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let old = try card("old", score: 80, topics: ["agents"], importance: "high")
        XCTAssertTrue(NotificationService.newImportantItems(in: [old], followed: ["agents"], defaults: defaults).isEmpty,
                      "first check only records a baseline")
        XCTAssertTrue(NotificationService.newImportantItems(in: [old], followed: ["agents"], defaults: defaults).isEmpty,
                      "already-seen items never alert")
    }

    func testFormatting() {
        XCTAssertEqual(Formatting.count(1_234), "1.2k")
        XCTAssertEqual(Formatting.count(56_000), "56k")
        XCTAssertEqual(Formatting.signed(-5), "-5")
        XCTAssertEqual(Formatting.perDay(3.24), "3.2")
        XCTAssertNotNil(DateParsing.parse("2026-10-20T12:00:00Z"))
    }
}
