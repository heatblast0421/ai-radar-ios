import SwiftUI

@MainActor
final class ItemDetailModel: ObservableObject {
    @Published var detail: ItemDetail?
    @Published var phase: LoadPhase = .idle
    @Published var staleSince: Date?
    let id: String

    init(id: String) { self.id = id }

    func load() async {
        let path = "items/\(id).json"
        if detail == nil, let cached = APIClient.shared.cached(path, as: ItemDetail.self) {
            detail = cached.value
            staleSince = cached.fetchedAt
            phase = .loaded
        }
        if detail == nil { phase = .loading }
        do {
            let loaded = try await APIClient.shared.get(path, as: ItemDetail.self)
            detail = loaded.value
            staleSince = loaded.isStale ? loaded.fetchedAt : nil
            phase = .loaded
        } catch {
            if detail == nil { phase = .failed(error.localizedDescription) }
        }
    }
}

struct ItemDetailView: View {
    @StateObject private var model: ItemDetailModel
    @EnvironmentObject private var prefs: Preferences
    @EnvironmentObject private var bookmarks: BookmarkStore
    @State private var level: SummaryLevel = .quick
    @State private var didSetLevel = false

    init(id: String) {
        _model = StateObject(wrappedValue: ItemDetailModel(id: id))
    }

    var body: some View {
        Group {
            switch model.phase {
            case .idle, .loading:
                LoadingView(message: "Loading details…")
            case .failed(let message):
                ErrorStateView(message: message) { Task { await model.load() } }
            case .loaded:
                if let detail = model.detail {
                    content(detail)
                }
            }
        }
        .background(Theme.screenBackground)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if !didSetLevel {
                level = prefs.summaryLevel
                didSetLevel = true
            }
            await model.load()
        }
        .refreshable { await model.load() }
    }

    @ViewBuilder private func content(_ detail: ItemDetail) -> some View {
        let card = detail.card
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let stale = model.staleSince { StaleBanner(fetchedAt: stale) }
                header(card)
                actions(card)
                Picker("Detail level", selection: $level) {
                    ForEach(SummaryLevel.allCases) { Text($0.title).tag($0) }
                }
                .pickerStyle(.segmented)

                switch level {
                case .quick: QuickLevelView(detail: detail)
                case .technical: TechnicalLevelView(detail: detail)
                case .explore: ExploreLevelView(detail: detail)
                }

                if let supporting = card.supporting, !supporting.isEmpty {
                    supportingSources(supporting)
                }
                RankingExplanationView(card: card)
                timestamps(card)
            }
            .padding()
        }
    }

    private func header(_ card: FeedCard) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Label(Theme.kindLabel(card.kind), systemImage: Theme.kindIcon(card.kind))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.accent)
                Text("· \(card.source.name)")
                    .font(.caption.weight(.semibold))
                if card.source.official == true {
                    Label("Official", systemImage: "checkmark.seal.fill")
                        .font(.caption2)
                        .foregroundStyle(.green)
                }
                Spacer()
                ImportanceBadge(importance: card.importance, reason: card.importanceReason)
            }
            Text(card.title)
                .font(.title2.weight(.bold))
                .fixedSize(horizontal: false, vertical: true)
            if let author = card.author, !author.isEmpty {
                Text(author).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack { ForEach(card.topics, id: \.self) { TopicChip(topic: $0) } }
            }
        }
    }

    private func actions(_ card: FeedCard) -> some View {
        HStack(spacing: 10) {
            ExternalLinkButton(title: "Open source", url: card.url, icon: "safari")
            if let d = card.discussionUrl, d != card.url {
                ExternalLinkButton(title: "Discussion", url: d, icon: "bubble.left.and.bubble.right")
            }
            Button {
                bookmarks.toggle(SavedEntry(card: card))
            } label: {
                Image(systemName: bookmarks.isSaved(card.id) ? "bookmark.fill" : "bookmark")
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.bordered)
            .accessibilityLabel(bookmarks.isSaved(card.id) ? "Remove bookmark" : "Bookmark")
            if let url = URL(string: card.url) {
                ShareLink(item: url) {
                    Image(systemName: "square.and.arrow.up").frame(width: 44, height: 44)
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("Share")
            }
        }
    }

    private func supportingSources(_ list: [SupportingSource]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Also reported by", icon: "square.stack.3d.up")
            ForEach(list) { s in
                if let url = URL(string: s.url) {
                    Link(destination: url) {
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(s.source).font(.caption.weight(.semibold)).foregroundStyle(Theme.accent)
                                Text(s.title ?? s.url).font(.subheadline).foregroundStyle(.primary)
                                    .multilineTextAlignment(.leading).lineLimit(2)
                            }
                            Spacer()
                            Image(systemName: "arrow.up.right").font(.caption).foregroundStyle(.secondary)
                        }
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 10).fill(Theme.cardBackground))
                    }
                }
            }
        }
    }

    private func timestamps(_ card: FeedCard) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Published: \(Formatting.date(card.publishedAt))")
            Text("Discovered by AI Radar: \(Formatting.date(card.discoveredAt))")
            if card.updatedAt != card.discoveredAt {
                Text("Last updated: \(Formatting.date(card.updatedAt))")
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }
}

// MARK: - Level 1

struct QuickLevelView: View {
    let detail: ItemDetail

    var body: some View {
        let quick = detail.extras.explanation?.quick
        let meta = detail.extras.explanation?.quickMeta
        VStack(alignment: .leading, spacing: 14) {
            if let quick, let summary = quick["summary"]?.text {
                ProvenanceBox(kind: .ai, title: "AI summary", subtitle: meta?.model) {
                    Text(summary).font(.body).fixedSize(horizontal: false, vertical: true)
                    if let why = quick["why_it_matters"]?.text {
                        Text("Why it matters").font(.subheadline.weight(.semibold)).padding(.top, 4)
                        Text(why).font(.subheadline).fixedSize(horizontal: false, vertical: true)
                    }
                    let terms = quick["key_terms"]?.terms ?? []
                    if !terms.isEmpty {
                        Text("Terms explained").font(.subheadline.weight(.semibold)).padding(.top, 4)
                        ForEach(Array(terms.enumerated()), id: \.offset) { _, t in
                            Text("\(Text(t.term).bold())\(t.meaning.isEmpty ? "" : ": " + t.meaning)")
                                .font(.subheadline)
                        }
                    }
                    if quick["source_is_thin"] == .bool(true) {
                        Label("The source says little; this summary is limited.", systemImage: "exclamationmark.circle")
                            .font(.caption).foregroundStyle(.orange)
                    }
                    WarningsView(warnings: meta?.warnings)
                    AILabel(text: detail.extras.explanation?.label)
                }
            } else {
                ProvenanceBox(kind: .info, title: "No AI summary yet") {
                    Text("AI summaries are written for the highest-ranked items as the daily AI budget allows. Below is the original source text.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
            }
            SourceTextView(detail: detail)
        }
    }
}

struct SourceTextView: View {
    let detail: ItemDetail
    @State private var expanded = false

    var body: some View {
        let text = detail.extras.sourceText ?? ""
        ProvenanceBox(kind: .verified, title: "From the source", subtitle: detail.card.source.name) {
            if text.isEmpty {
                Text("The source provided only a title. Open the original to read more.")
                    .font(.subheadline).foregroundStyle(.secondary)
            } else {
                Text(text)
                    .font(.subheadline)
                    .lineLimit(expanded ? nil : 8)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if text.count > 450 {
                    Button(expanded ? "Show less" : "Show more") { withAnimation { expanded.toggle() } }
                        .font(.footnote.weight(.semibold))
                        .frame(minHeight: 44)
                }
            }
            Text(detail.extras.sourceTextNote ?? "Excerpt from the original source.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }
}

struct WarningsView: View {
    let warnings: [String]?
    var body: some View {
        if let warnings, !warnings.isEmpty {
            Label("These figures don't appear in the source; treat them with caution: \(warnings.joined(separator: ", "))",
                  systemImage: "exclamationmark.triangle")
                .font(.caption)
                .foregroundStyle(.orange)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

struct AILabel: View {
    let text: String?
    var body: some View {
        Text(text ?? "AI-generated interpretation. May contain mistakes; verify important details.")
            .font(.caption2)
            .foregroundStyle(.secondary)
    }
}

// MARK: - Level 2

struct TechnicalLevelView: View {
    let detail: ItemDetail

    var body: some View {
        let deep = detail.extras.explanation?.deep
        let meta = detail.extras.explanation?.deepMeta
        VStack(alignment: .leading, spacing: 14) {
            if let deep {
                ProvenanceBox(kind: .ai, title: "Technical explanation", subtitle: meta?.model) {
                    block("In plain words", deep["plain_explanation"])
                    block("How it works", deep["how_it_works"])
                    block("What changed", deep["what_changed"])
                    block("Why it matters", deep["why_it_matters"])
                    block("Compared with existing approaches", deep["comparison"])
                    list("Strengths", deep["strengths"])
                    list("Limitations", deep["limitations"])
                    list("Use cases", deep["use_cases"])
                    let glossary = deep["glossary"]?.terms ?? []
                    if !glossary.isEmpty {
                        Text("Glossary").font(.subheadline.weight(.semibold))
                        ForEach(Array(glossary.enumerated()), id: \.offset) { _, t in
                            Text("\(Text(t.term).bold())\(t.meaning.isEmpty ? "" : ": " + t.meaning)").font(.subheadline)
                        }
                    }
                    WarningsView(warnings: meta?.warnings)
                    AILabel(text: detail.extras.explanation?.label)
                }
                if let evidence = deep["evidence"] {
                    EvidenceView(evidence: evidence)
                }
            } else {
                ProvenanceBox(kind: .info, title: "No technical deep-dive yet") {
                    Text("Deep-dives are generated for the most important items each day (limited by the free AI quota). You can still read the verified source text below and open the original.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
            }
            SourceTextView(detail: detail)
        }
    }

    @ViewBuilder private func block(_ title: String, _ value: JSONValue?) -> some View {
        if let text = value?.text {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.subheadline.weight(.semibold))
                Text(text).font(.subheadline).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    @ViewBuilder private func list(_ title: String, _ value: JSONValue?) -> some View {
        let items = value?.list ?? []
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(.subheadline.weight(.semibold))
                BulletList(items: items).font(.subheadline)
            }
        }
    }
}

struct EvidenceView: View {
    let evidence: JSONValue

    var body: some View {
        ProvenanceBox(kind: .info, title: "Evidence check", subtitle: "What the source claims vs. shows") {
            let claims = evidence["claims"]?.list ?? []
            if !claims.isEmpty {
                Text("Claims made by the source").font(.subheadline.weight(.semibold))
                BulletList(items: claims).font(.subheadline)
            }
            if let given = evidence["evidence_given"]?.text {
                Text("Evidence provided").font(.subheadline.weight(.semibold))
                Text(given).font(.subheadline)
            }
            let unverified = evidence["unverified"]?.list ?? []
            if !unverified.isEmpty {
                Text("Verify independently").font(.subheadline.weight(.semibold))
                BulletList(items: unverified).font(.subheadline)
            }
            Text("This check is AI-assisted. It only reflects what the source text contains.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }
}

// MARK: - Level 3

struct ExploreLevelView: View {
    let detail: ItemDetail

    var body: some View {
        let explore = detail.extras.explanation?.deep?["explore"]
        VStack(alignment: .leading, spacing: 14) {
            if let explore {
                ProvenanceBox(kind: .ai, title: "Explore & build", subtitle: "Suggestions") {
                    section("Try this", explore["experiments"])
                    section("Project ideas", explore["implementation_ideas"])
                    section("Questions worth investigating", explore["questions"])
                    let terms = explore["search_terms"]?.list ?? []
                    if !terms.isEmpty {
                        Text("Search further").font(.subheadline.weight(.semibold))
                        ForEach(terms, id: \.self) { term in
                            searchLink(term, base: "https://github.com/search?type=repositories&q=", icon: "magnifyingglass")
                        }
                    }
                    AILabel(text: "AI-generated suggestions. Links below are real sources from AI Radar's index.")
                }
            } else {
                ProvenanceBox(kind: .info, title: "No AI suggestions yet") {
                    Text("Experiments and project ideas are generated alongside technical deep-dives for the most important items. Related links below come from AI Radar's own index.")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
            }

            if let links = detail.extras.links, !links.isEmpty {
                SectionHeader(title: "Links", icon: "link")
                ForEach(links) { link in
                    ExternalLinkButton(title: link.title, url: link.url)
                }
            }

            if let repos = detail.extras.relatedRepos, !repos.isEmpty {
                SectionHeader(title: "Related repositories", icon: "chevron.left.forwardslash.chevron.right")
                ForEach(repos) { repo in
                    NavigationLink(value: Route.repo(repo.fileId)) {
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(repo.fullName).font(.subheadline.weight(.semibold))
                                if let d = repo.description {
                                    Text(d).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                }
                            }
                            Spacer()
                            Label(Formatting.count(repo.stars), systemImage: "star").font(.caption).foregroundStyle(.secondary)
                        }
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 10).fill(Theme.cardBackground))
                    }
                    .buttonStyle(.plain)
                }
            }

            if let related = detail.extras.related, !related.isEmpty {
                SectionHeader(title: "Related on AI Radar", icon: "point.3.connected.trianglepath.dotted")
                ForEach(related) { item in
                    NavigationLink(value: Route.item(item.id)) {
                        HStack(alignment: .top) {
                            Image(systemName: Theme.kindIcon(item.kind ?? "article")).foregroundStyle(Theme.accent)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(item.title).font(.subheadline).multilineTextAlignment(.leading).lineLimit(2)
                                Text("\(item.source ?? "") · \(Formatting.relative(iso: item.publishedAt))")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                        }
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 10).fill(Theme.cardBackground))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    @ViewBuilder private func section(_ title: String, _ value: JSONValue?) -> some View {
        let items = value?.list ?? []
        if !items.isEmpty {
            Text(title).font(.subheadline.weight(.semibold))
            BulletList(items: items).font(.subheadline)
        }
    }

    @ViewBuilder private func searchLink(_ term: String, base: String, icon: String) -> some View {
        if let encoded = term.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
           let url = URL(string: base + encoded) {
            Link(destination: url) {
                Label(term, systemImage: icon)
                    .font(.subheadline)
                    .frame(maxWidth: .infinity, minHeight: 36, alignment: .leading)
            }
        }
    }
}

// MARK: - Ranking transparency

struct RankingExplanationView: View {
    let card: FeedCard
    @State private var expanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: 8) {
                if let parts = card.scoreParts {
                    bar("Relevance to AI engineering", parts.relevance, weight: 28)
                    bar("Freshness", parts.freshness, weight: 22)
                    bar("Source credibility", parts.credibility, weight: 15)
                    bar("Community engagement", parts.engagement, weight: 22)
                    bar("Significance (rule-based)", parts.significance, weight: 13)
                }
                if let reason = card.importanceReason {
                    Text("Marked \(card.importance ?? ""): \(reason)").font(.caption)
                }
                Text("Score \(Int(card.score.rounded())) / 100. Rankings use transparent rules, never an AI's opinion. Official launches and security news are guaranteed visibility.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            .padding(.top, 8)
        } label: {
            Label("Why it's ranked here", systemImage: "chart.bar.xaxis")
                .font(.subheadline.weight(.semibold))
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: Theme.corner).fill(Theme.cardBackground))
    }

    private func bar(_ title: String, _ value: Double?, weight: Int) -> some View {
        let v = max(0, min(1, value ?? 0))
        return VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(title).font(.caption)
                Spacer()
                Text("\(Int((v * 100).rounded()))% · weight \(weight)%").font(.caption2).foregroundStyle(.secondary)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.secondary.opacity(0.15))
                    Capsule().fill(Theme.accent).frame(width: geo.size.width * v)
                }
            }
            .frame(height: 6)
        }
        .accessibilityElement(children: .combine)
    }
}
