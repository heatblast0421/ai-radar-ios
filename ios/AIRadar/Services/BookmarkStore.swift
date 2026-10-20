import Foundation

/// A saved item. Stores enough to show it in Saved even when offline.
struct SavedEntry: Codable, Identifiable, Hashable {
    enum Kind: String, Codable { case item, repo }

    let id: String          // item id, or repo id ("owner/name")
    let kind: Kind
    let itemKind: String    // article | paper | discussion | release | model | repo
    let title: String
    let summary: String?
    let url: String
    let source: String?
    let topics: [String]
    let savedAt: Date

    var categoryTitle: String {
        switch itemKind {
        case "paper": return "Papers"
        case "repo": return "Repositories"
        case "release": return "Releases"
        case "model": return "Models"
        case "discussion": return "Discussions"
        default: return "Articles"
        }
    }
}

/// Bookmarks persisted as JSON in Application Support, so they survive app restarts and updates.
@MainActor
final class BookmarkStore: ObservableObject {
    @Published private(set) var entries: [SavedEntry] = []
    private let fileURL: URL

    init(fileURL: URL? = nil) {
        if let fileURL {
            self.fileURL = fileURL
        } else {
            let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            self.fileURL = dir.appendingPathComponent("bookmarks.json")
        }
        load()
    }

    func isSaved(_ id: String) -> Bool {
        entries.contains { $0.id == id }
    }

    func toggle(_ entry: SavedEntry) {
        if isSaved(entry.id) {
            remove(id: entry.id)
        } else {
            entries.insert(entry, at: 0)
            persist()
        }
    }

    func remove(id: String) {
        entries.removeAll { $0.id == id }
        persist()
    }

    func remove(atOffsets offsets: IndexSet, in list: [SavedEntry]) {
        let ids = offsets.map { list[$0].id }
        entries.removeAll { ids.contains($0.id) }
        persist()
    }

    /// Topic counts of saved items, used to personalise "For You".
    var topicAffinity: [String: Int] {
        var counts: [String: Int] = [:]
        for e in entries {
            for t in e.topics { counts[t, default: 0] += 1 }
        }
        return counts
    }

    private func load() {
        guard let data = try? Data(contentsOf: fileURL) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        entries = (try? decoder.decode([SavedEntry].self, from: data)) ?? []
    }

    private func persist() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(entries) {
            try? data.write(to: fileURL, options: .atomic)
        }
    }
}

extension SavedEntry {
    init(card: FeedCard) {
        self.init(id: card.id, kind: .item, itemKind: card.kind, title: card.title, summary: card.summary,
                  url: card.url, source: card.source.name, topics: card.topics, savedAt: Date())
    }

    init(repo: RepoCard) {
        self.init(id: repo.id, kind: .repo, itemKind: "repo", title: repo.fullName,
                  summary: repo.aiSummary ?? repo.description, url: repo.url, source: "GitHub",
                  topics: repo.categories ?? [], savedAt: Date())
    }
}
