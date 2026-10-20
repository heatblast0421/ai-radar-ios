import Foundation

// Models for the static JSON API published by the backend (see backend/airadar/export.py).
// JSON keys are snake_case and decoded with `.convertFromSnakeCase`. Everything that might be
// missing is optional so an older/newer backend never crashes the app.

struct SourceRef: Decodable, Hashable {
    let id: String
    let name: String
    let credibility: Double?
    let official: Bool?
    let group: String?
}

struct Metrics: Decodable, Hashable {
    var hnPoints: Int?
    var hnComments: Int?
    var hfUpvotes: Int?
    var hfComments: Int?
    var hfLikes: Int?
    var hfDownloads: Int?
    var stars: Int?
    var forks: Int?
}

struct SupportingSource: Decodable, Hashable, Identifiable {
    let title: String?
    let url: String
    let source: String
    let itemId: String?
    let publishedAt: String?
    var id: String { url }
}

struct ScoreParts: Decodable, Hashable {
    let relevance: Double?
    let freshness: Double?
    let credibility: Double?
    let engagement: Double?
    let significance: Double?
}

struct FeedCard: Decodable, Hashable, Identifiable {
    let id: String
    let kind: String
    let title: String
    let summary: String?
    let summaryKind: String?
    let whyItMatters: String?
    let url: String
    let discussionUrl: String?
    let source: SourceRef
    let author: String?
    let publishedAt: String?
    let discoveredAt: String?
    let updatedAt: String?
    let topics: [String]
    let sections: [String]?
    let score: Double
    let trendingScore: Double?
    let importance: String?
    let importanceReason: String?
    let scoreParts: ScoreParts?
    let metrics: Metrics?
    let supporting: [SupportingSource]?
    let hasDeep: Bool?
    let repo: String?
    let releaseKind: String?

    var isAISummary: Bool { summaryKind == "ai" }
    var publishedDate: Date? { DateParsing.parse(publishedAt) ?? DateParsing.parse(discoveredAt) }
    var discoveredDate: Date? { DateParsing.parse(discoveredAt) }
}

struct FeedPage: Decodable {
    let section: String?
    let sort: String?
    let description: String?
    let page: Int
    let totalPages: Int
    let total: Int
    let generatedAt: String?
    let items: [FeedCard]
}

struct LinkRef: Decodable, Hashable, Identifiable {
    let title: String
    let url: String
    let kind: String?
    var id: String { url }
}

struct RelatedItem: Decodable, Hashable, Identifiable {
    let id: String
    let title: String
    let url: String
    let kind: String?
    let source: String?
    let publishedAt: String?
}

struct RelatedRepo: Decodable, Hashable, Identifiable {
    let id: String
    let fullName: String
    let description: String?
    let stars: Int?
    let url: String
    var fileId: String { id.replacingOccurrences(of: "/", with: "__") }
}

struct ExplanationMeta: Decodable, Hashable {
    let provider: String?
    let model: String?
    let generatedAt: String?
    let warnings: [String]?
}

/// AI-generated interpretation. `quick` and `deep` are loosely typed (see JSONValue).
struct Explanation: Decodable, Hashable {
    let label: String?
    let quick: JSONValue?
    let deep: JSONValue?
    let quickMeta: ExplanationMeta?
    let deepMeta: ExplanationMeta?
}

struct DetailExtras: Decodable {
    let sourceText: String?
    let sourceTextNote: String?
    let links: [LinkRef]?
    let explanation: Explanation?
    let related: [RelatedItem]?
    let relatedRepos: [RelatedRepo]?
}

struct ItemDetail: Decodable {
    let card: FeedCard
    let extras: DetailExtras

    init(from decoder: Decoder) throws {
        card = try FeedCard(from: decoder)
        extras = try DetailExtras(from: decoder)
    }
}

// MARK: - GitHub

struct ReleaseRef: Decodable, Hashable {
    let tag: String?
    let name: String?
    let publishedAt: String?
    let url: String?
}

struct RepoGrowth: Decodable, Hashable {
    let trendAvailable: Bool?
    let starsDay: Int?
    let starsWeek: Int?
    let starsPerDayMeasured: Double?
    let measuredWindowHours: Double?
    let avgStarsPerDaySinceCreation: Double?
    let trackingSince: String?
    let snapshotsCount: Int?
}

struct SpottedOn: Decodable, Hashable {
    let label: String?
    let link: String?
    let at: String?
}

struct RepoCard: Decodable, Hashable, Identifiable {
    let id: String
    let fileId: String
    let fullName: String
    let owner: String
    let name: String
    let description: String?
    let aiSummary: String?
    let language: String?
    let stars: Int
    let forks: Int
    let openIssues: Int?
    let createdAt: String?
    let pushedAt: String?
    let firstSeenAt: String?
    let lastCheckedAt: String?
    let latestRelease: ReleaseRef?
    let topics: [String]?
    let categories: [String]?
    let url: String
    let homepage: String?
    let license: String?
    let score: Double?
    let emergingScore: Double?
    let curated: Bool?
    let growth: RepoGrowth?
    let spottedOn: [SpottedOn]?
    let itemId: String?
}

struct RepoPage: Decodable {
    let sort: String?
    let description: String?
    let page: Int
    let totalPages: Int
    let total: Int
    let generatedAt: String?
    let items: [RepoCard]
}

struct Snapshot: Decodable, Hashable, Identifiable {
    let t: String
    let stars: Int
    let forks: Int?
    var id: String { t }
    var date: Date? { DateParsing.parse(t) }
}

struct ReleaseInfo: Decodable, Hashable, Identifiable {
    let tag: String
    let name: String?
    let url: String?
    let publishedAt: String?
    let prerelease: Int?
    let bodyExcerpt: String?
    var id: String { tag }
}

struct RepoDetailExtras: Decodable {
    let readmeExcerpt: String?
    let snapshots: [Snapshot]?
    let releases: [ReleaseInfo]?
    let explanation: Explanation?
}

struct RepoDetail: Decodable {
    let card: RepoCard
    let extras: RepoDetailExtras

    init(from decoder: Decoder) throws {
        card = try RepoCard(from: decoder)
        extras = try RepoDetailExtras(from: decoder)
    }
}

// MARK: - Meta, briefing, search

struct TopicInfo: Decodable, Hashable, Identifiable {
    let id: String
    let name: String
    let description: String?
}

struct SourceStatus: Decodable, Hashable, Identifiable {
    let id: String
    let name: String
    let kind: String?
    let group: String?
    let url: String?
    let status: String
    let credibility: Double?
    let official: Bool?
    let lastSuccessAt: String?
    let lastAttemptAt: String?
    let lastError: String?
    let items: Int?
    let refreshMinutes: Int?
}

struct LLMStatus: Decodable, Hashable {
    let configured: Bool
    let provider: String?
    let model: String?
    let callsDay: Int?
    let successfulDay: Int?
    let lastCallAt: String?
    let lastError: String?
    let lastErrorAt: String?
    let explanationsCached: Int?
}

struct Meta: Decodable {
    let apiVersion: Int
    let generatedAt: String
    let status: String
    let counts: [String: Int]?
    let sources: [SourceStatus]
    let failingSources: Int?
    let topics: [TopicInfo]
    let llm: LLMStatus?
    let briefingDay: String?
    let notes: [String]?
}

struct BriefingBullet: Decodable, Hashable, Identifiable {
    let text: String
    let itemIds: [String]?
    var id: String { text }
}

struct Briefing: Decodable {
    let available: Bool
    let message: String?
    let day: String?
    let generatedAt: String?
    let kind: String?
    let label: String?
    let headline: String?
    let overview: String?
    let bullets: [BriefingBullet]?
    let watchNext: [String]?
    let items: [FeedCard]?
}

struct SearchEntry: Decodable, Hashable, Identifiable {
    let id: String
    let t: String
    let kind: String
    let title: String
    let summary: String?
    let topics: [String]?
    let sections: [String]?
    let source: String?
    let url: String
    let publishedAt: String?
    let score: Double?
    let stars: Int?
    var isRepo: Bool { t == "repo" }
}

struct SearchIndex: Decodable {
    let generatedAt: String?
    let count: Int
    let entries: [SearchEntry]
}

// MARK: - Dates

enum DateParsing {
    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static func parse(_ string: String?) -> Date? {
        guard let s = string, !s.isEmpty else { return nil }
        return iso.date(from: s) ?? isoFractional.date(from: s)
    }
}
