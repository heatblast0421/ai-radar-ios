import SwiftUI

/// Research over everything AI Radar has indexed (articles, papers, releases, models and repositories).
/// Runs on the phone over the published index, so it works offline after the first load.
@MainActor
final class SearchModel: ObservableObject {
    @Published var index: SearchIndex?
    @Published var phase: LoadPhase = .idle
    @Published var staleSince: Date?

    func load() async {
        await Task { await self.performLoad() }.value
    }

    private func performLoad() async {
        if index == nil, let cached = APIClient.shared.cached("search.json", as: SearchIndex.self) {
            index = cached.value
            staleSince = cached.fetchedAt
            phase = .loaded
        }
        if index == nil { phase = .loading }
        do {
            let loaded = try await APIClient.shared.get("search.json", as: SearchIndex.self)
            index = loaded.value
            staleSince = loaded.isStale ? loaded.fetchedAt : nil
            phase = .loaded
        } catch {
            if index == nil { phase = .failed(error.localizedDescription) }
        }
    }

    /// Keyword search: every word must match title, summary, topics or source. Ranked by
    /// title matches first, then the item's own score.
    func results(for query: String, kind: String?) -> [SearchEntry] {
        guard let entries = index?.entries else { return [] }
        let words = query.lowercased().split(whereSeparator: { $0 == " " || $0 == "," }).map(String.init).filter { $0.count > 1 }
        guard !words.isEmpty else { return [] }
        let scored: [(SearchEntry, Double)] = entries.compactMap { e in
            if let kind, kind != e.kind { return nil }
            let title = e.title.lowercased()
            let hay = title + " " + (e.summary ?? "").lowercased() + " " + (e.topics ?? []).joined(separator: " ") + " " + (e.source ?? "").lowercased()
            var score = 0.0
            for w in words {
                let syn = SearchModel.synonyms[w] ?? [w]
                guard syn.contains(where: { hay.contains($0) }) else { return nil }
                if syn.contains(where: { title.contains($0) }) { score += 10 }
            }
            return (e, score + (e.score ?? 0) / 10)
        }
        return scored.sorted { $0.1 > $1.1 }.prefix(80).map { $0.0 }
    }

    static let synonyms: [String: [String]] = [
        "agent": ["agent"], "agents": ["agent"], "mcp": ["mcp", "model context protocol"],
        "rag": ["rag", "retrieval"], "memory": ["memory", "context"], "eval": ["eval", "benchmark"],
        "evals": ["eval", "benchmark"], "inference": ["inference", "serving", "quantiz"], "llm": ["llm", "language model"],
    ]

    struct Suggestion: Identifiable {
        let title: String
        let query: String
        var id: String { title }
    }

    static let suggestions: [Suggestion] = [
        Suggestion(title: "Agent frameworks", query: "agent framework"),
        Suggestion(title: "Agent memory", query: "agent memory"),
        Suggestion(title: "MCP servers", query: "mcp server"),
        Suggestion(title: "RAG & retrieval", query: "rag"),
        Suggestion(title: "Evals & benchmarks", query: "eval"),
        Suggestion(title: "Inference speed-ups", query: "inference"),
        Suggestion(title: "Coding agents", query: "coding agent"),
        Suggestion(title: "New open models", query: "open model"),
    ]
}

struct SearchScreen: View {
    @StateObject private var model = SearchModel()
    @State private var query = ""
    @State private var kind: String?

    private struct KindOption: Identifiable {
        let value: String?
        let title: String
        var id: String { title }
    }

    private let kinds: [KindOption] = [
        KindOption(value: nil, title: "All"), KindOption(value: "repo", title: "Repos"),
        KindOption(value: "paper", title: "Papers"), KindOption(value: "article", title: "Articles"),
        KindOption(value: "release", title: "Releases"), KindOption(value: "discussion", title: "Discussions"),
        KindOption(value: "model", title: "Models"),
    ]

    var body: some View {
        List {
            switch model.phase {
            case .idle, .loading:
                LoadingView(message: "Loading the search index…").listRowBackground(Color.clear)
            case .failed(let message):
                ErrorStateView(message: message) { Task { await model.load() } }.listRowBackground(Color.clear)
            case .loaded:
                if let stale = model.staleSince {
                    StaleBanner(fetchedAt: stale).listRowInsets(EdgeInsets()).listRowBackground(Color.clear)
                }
                Section {
                    Picker("Type", selection: $kind) {
                        ForEach(kinds) { option in Text(option.title).tag(option.value) }
                    }
                    .pickerStyle(.menu)
                }
                if query.trimmingCharacters(in: .whitespaces).count < 2 {
                    Section {
                        ForEach(SearchModel.suggestions) { s in
                            Button {
                                query = s.query
                            } label: {
                                Label(s.title, systemImage: "magnifyingglass")
                            }
                            .frame(minHeight: 36)
                        }
                    } header: {
                        Text("Try a research question")
                    } footer: {
                        Text("Searches \(model.index?.count ?? 0) items AI Radar collected over the last 45 days: titles, summaries and topics. Every result links to its original source.")
                    }
                } else {
                    let results = model.results(for: query, kind: kind)
                    Section {
                        if results.isEmpty {
                            Text("No matches. Try fewer or broader words.").foregroundStyle(.secondary)
                        }
                        ForEach(results) { r in
                            NavigationLink(value: r.isRepo ? Route.repo(r.id.replacingOccurrences(of: "/", with: "__")) : Route.item(r.id)) {
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack(spacing: 6) {
                                        Image(systemName: Theme.kindIcon(r.kind)).foregroundStyle(Theme.accent)
                                        Text(r.source ?? "").font(.caption.weight(.semibold))
                                        if let stars = r.stars {
                                            Label(Formatting.count(stars), systemImage: "star").font(.caption).foregroundStyle(.secondary)
                                        }
                                        Text(Formatting.relative(iso: r.publishedAt)).font(.caption).foregroundStyle(.secondary)
                                    }
                                    Text(r.title).font(.subheadline.weight(.semibold)).lineLimit(3)
                                    if let s = r.summary, !s.isEmpty {
                                        Text(s).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                    }
                                }
                                .padding(.vertical, 2)
                            }
                        }
                    } header: {
                        Text("\(results.count) result\(results.count == 1 ? "" : "s")")
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Search")
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "e.g. agent memory, MCP, vLLM")
        .task { await model.load() }
        .refreshable { await model.load() }
    }
}
