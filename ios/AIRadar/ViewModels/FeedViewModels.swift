import SwiftUI

enum LoadPhase: Equatable {
    case idle, loading, loaded
    case failed(String)
}

enum FeedSort: String, CaseIterable, Identifiable {
    case forYou, top, latest, trending
    var id: String { rawValue }
    var title: String {
        switch self {
        case .forYou: return "For You"
        case .top: return "Top"
        case .latest: return "Latest"
        case .trending: return "Trending"
        }
    }
    /// Server path component ("For You" is the Top list re-ranked on the phone).
    var path: String { self == .forYou ? "top" : rawValue }
}

/// Loads a paged feed for one section (pulse, research, lab, industry).
@MainActor
final class FeedViewModel: ObservableObject {
    let section: String
    @Published private(set) var cards: [FeedCard] = []
    @Published private(set) var phase: LoadPhase = .idle
    @Published private(set) var isLoadingMore = false
    @Published private(set) var staleSince: Date?
    @Published private(set) var sectionDescription: String?
    @Published private(set) var total = 0
    @Published var sort: FeedSort
    @Published var topic: String?

    private var page = 0
    private var totalPages = 1
    private var generation = 0
    private let api: APIClient

    init(section: String, sort: FeedSort, api: APIClient = .shared) {
        self.section = section
        self.sort = sort
        self.api = api
    }

    var hasMore: Bool { page < totalPages }

    private func path(_ page: Int) -> String { "feed/\(section)/\(sort.path)/\(page).json" }

    func loadIfNeeded() async {
        if phase == .idle { await reload() }
    }

    func changeSort(_ newSort: FeedSort) async {
        guard newSort != sort else { return }
        let samePath = newSort.path == sort.path
        sort = newSort
        if !samePath {
            cards = []
            await reload()
        }
    }

    func reload() async {
        generation += 1
        let gen = generation
        if cards.isEmpty, let cached = api.cached(path(1), as: FeedPage.self) {
            apply(cached.value, replace: true)
            staleSince = cached.fetchedAt
        }
        if cards.isEmpty { phase = .loading }
        do {
            let loaded = try await api.get(path(1), as: FeedPage.self)
            guard gen == generation else { return }
            apply(loaded.value, replace: true)
            staleSince = loaded.isStale ? loaded.fetchedAt : nil
            phase = .loaded
        } catch {
            guard gen == generation else { return }
            if (error as? URLError)?.code == .cancelled { return }
            if cards.isEmpty {
                phase = .failed(error.localizedDescription)
            } else {
                phase = .loaded
            }
        }
    }

    func loadMore() async {
        guard hasMore, !isLoadingMore, phase == .loaded else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        let gen = generation
        do {
            let loaded = try await api.get(path(page + 1), as: FeedPage.self)
            guard gen == generation else { return }
            apply(loaded.value, replace: false)
        } catch {
            // Keep what we have; the footer offers a retry.
            totalPages = page
        }
    }

    private func apply(_ value: FeedPage, replace: Bool) {
        sectionDescription = value.description
        total = value.total
        totalPages = value.totalPages
        page = value.page
        if replace {
            cards = value.items
        } else {
            let known = Set(cards.map(\.id))
            cards.append(contentsOf: value.items.filter { !known.contains($0.id) })
        }
    }

    /// Cards after topic filter and on-screen search.
    func visible(search: String, followed: Set<String>, affinity: [String: Int]) -> [FeedCard] {
        var list = cards
        if let topic { list = list.filter { $0.topics.contains(topic) } }
        let q = search.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !q.isEmpty {
            list = list.filter {
                $0.title.lowercased().contains(q) || ($0.summary ?? "").lowercased().contains(q) ||
                    $0.source.name.lowercased().contains(q)
            }
        }
        if sort == .forYou {
            list = PersonalRanker.rank(list, followed: followed, affinity: affinity).map(\.card)
        }
        return list
    }
}

enum RepoSort: String, CaseIterable, Identifiable {
    case emerging, growing, stars, new, releases
    var id: String { rawValue }
    var title: String {
        switch self {
        case .emerging: return "Emerging"
        case .growing: return "Fastest growing"
        case .stars: return "Most stars"
        case .new: return "Newest"
        case .releases: return "New releases"
        }
    }
}

@MainActor
final class RepoListViewModel: ObservableObject {
    @Published private(set) var repos: [RepoCard] = []
    @Published private(set) var phase: LoadPhase = .idle
    @Published private(set) var isLoadingMore = false
    @Published private(set) var staleSince: Date?
    @Published private(set) var sortDescription: String?
    @Published private(set) var total = 0
    @Published private(set) var sort: RepoSort = .emerging
    @Published var category: String?

    private var page = 0
    private var totalPages = 1
    private var generation = 0
    private let api: APIClient

    init(api: APIClient = .shared) { self.api = api }

    var hasMore: Bool { page < totalPages }
    private func path(_ page: Int) -> String { "github/\(sort.rawValue)/\(page).json" }

    func loadIfNeeded() async { if phase == .idle { await reload() } }

    func changeSort(_ newSort: RepoSort) async {
        guard newSort != sort else { return }
        sort = newSort
        repos = []
        await reload()
    }

    func reload() async {
        generation += 1
        let gen = generation
        if repos.isEmpty, let cached = api.cached(path(1), as: RepoPage.self) {
            apply(cached.value, replace: true)
            staleSince = cached.fetchedAt
        }
        if repos.isEmpty { phase = .loading }
        do {
            let loaded = try await api.get(path(1), as: RepoPage.self)
            guard gen == generation else { return }
            apply(loaded.value, replace: true)
            staleSince = loaded.isStale ? loaded.fetchedAt : nil
            phase = .loaded
        } catch {
            guard gen == generation else { return }
            if (error as? URLError)?.code == .cancelled { return }
            phase = repos.isEmpty ? .failed(error.localizedDescription) : .loaded
        }
    }

    func loadMore() async {
        guard hasMore, !isLoadingMore, phase == .loaded else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        let gen = generation
        do {
            let loaded = try await api.get(path(page + 1), as: RepoPage.self)
            guard gen == generation else { return }
            apply(loaded.value, replace: false)
        } catch {
            totalPages = page
        }
    }

    private func apply(_ value: RepoPage, replace: Bool) {
        sortDescription = value.description
        total = value.total
        totalPages = value.totalPages
        page = value.page
        if replace {
            repos = value.items
        } else {
            let known = Set(repos.map(\.id))
            repos.append(contentsOf: value.items.filter { !known.contains($0.id) })
        }
    }

    func visible(search: String) -> [RepoCard] {
        var list = repos
        if let category { list = list.filter { ($0.categories ?? []).contains(category) } }
        let q = search.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !q.isEmpty {
            list = list.filter {
                $0.fullName.lowercased().contains(q) || ($0.description ?? "").lowercased().contains(q) ||
                    ($0.topics ?? []).contains { $0.lowercased().contains(q) }
            }
        }
        return list
    }
}

/// App-wide data: server status (meta) and the daily briefing.
@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var meta: Meta?
    @Published private(set) var metaFetchedAt: Date?
    @Published private(set) var metaIsStale = false
    @Published private(set) var metaError: String?
    @Published private(set) var briefing: Briefing?
    @Published private(set) var briefingError: String?
    @Published var pendingItemId: String?   // opened from a notification

    private let api: APIClient
    init(api: APIClient = .shared) { self.api = api }

    var topics: [TopicInfo] {
        if let meta, !meta.topics.isEmpty { return meta.topics }
        return TopicNames.order.map { TopicInfo(id: $0, name: TopicNames.name($0), description: nil) }
    }

    func refresh() async {
        await loadMeta()
        await loadBriefing()
    }

    func loadMeta() async {
        if meta == nil, let cached = api.cached("meta.json", as: Meta.self) {
            meta = cached.value
            metaFetchedAt = cached.fetchedAt
            metaIsStale = true
        }
        do {
            let loaded = try await api.get("meta.json", as: Meta.self)
            meta = loaded.value
            metaFetchedAt = loaded.fetchedAt
            metaIsStale = loaded.isStale
            metaError = nil
        } catch {
            metaError = error.localizedDescription
        }
    }

    func loadBriefing() async {
        if briefing == nil, let cached = api.cached("briefing.json", as: Briefing.self) {
            briefing = cached.value
        }
        do {
            briefing = try await api.get("briefing.json", as: Briefing.self).value
            briefingError = nil
        } catch {
            briefingError = error.localizedDescription
        }
    }
}
