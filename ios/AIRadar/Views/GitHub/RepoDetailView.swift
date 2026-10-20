import Charts
import SwiftUI

@MainActor
final class RepoDetailModel: ObservableObject {
    @Published var detail: RepoDetail?
    @Published var phase: LoadPhase = .idle
    @Published var staleSince: Date?
    let fileId: String

    init(fileId: String) { self.fileId = fileId }

    func load() async {
        let path = "repos/\(fileId).json"
        if detail == nil, let cached = APIClient.shared.cached(path, as: RepoDetail.self) {
            detail = cached.value
            staleSince = cached.fetchedAt
            phase = .loaded
        }
        if detail == nil { phase = .loading }
        do {
            let loaded = try await APIClient.shared.get(path, as: RepoDetail.self)
            detail = loaded.value
            staleSince = loaded.isStale ? loaded.fetchedAt : nil
            phase = .loaded
        } catch {
            if detail == nil { phase = .failed(error.localizedDescription) }
        }
    }
}

struct RepoDetailView: View {
    @StateObject private var model: RepoDetailModel
    @EnvironmentObject private var bookmarks: BookmarkStore

    init(fileId: String) {
        _model = StateObject(wrappedValue: RepoDetailModel(fileId: fileId))
    }

    var body: some View {
        Group {
            switch model.phase {
            case .idle, .loading:
                LoadingView(message: "Loading repository…")
            case .failed(let message):
                ErrorStateView(message: message) { Task { await model.load() } }
            case .loaded:
                if let d = model.detail { content(d) }
            }
        }
        .background(Theme.screenBackground)
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load() }
        .refreshable { await model.load() }
    }

    @ViewBuilder private func content(_ d: RepoDetail) -> some View {
        let repo = d.card
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let stale = model.staleSince { StaleBanner(fetchedAt: stale) }
                VStack(alignment: .leading, spacing: 6) {
                    Text(repo.owner).font(.subheadline).foregroundStyle(.secondary)
                    Text(repo.name).font(.title.weight(.bold))
                    if let desc = repo.description {
                        Text(desc).font(.body).fixedSize(horizontal: false, vertical: true)
                    }
                }
                HStack(spacing: 10) {
                    ExternalLinkButton(title: "Open on GitHub", url: repo.url, icon: "safari")
                    Button {
                        bookmarks.toggle(SavedEntry(repo: repo))
                    } label: {
                        Image(systemName: bookmarks.isSaved(repo.id) ? "bookmark.fill" : "bookmark").frame(width: 44, height: 44)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityLabel(bookmarks.isSaved(repo.id) ? "Remove bookmark" : "Bookmark")
                    if let url = URL(string: repo.url) {
                        ShareLink(item: url) { Image(systemName: "square.and.arrow.up").frame(width: 44, height: 44) }
                            .buttonStyle(.bordered)
                            .accessibilityLabel("Share")
                    }
                }
                statsGrid(repo)
                growthSection(repo, snapshots: d.extras.snapshots ?? [])
                if let expl = d.extras.explanation, let quick = expl.quick, let summary = quick["summary"]?.text {
                    ProvenanceBox(kind: .ai, title: "AI summary", subtitle: expl.quickMeta?.model) {
                        Text(summary).font(.subheadline)
                        if let why = quick["why_it_matters"]?.text {
                            Text("Why it matters: \(why)").font(.subheadline)
                        }
                        if let plain = expl.deep?["how_it_works"]?.text {
                            Text("How it works").font(.subheadline.weight(.semibold))
                            Text(plain).font(.subheadline)
                        }
                        let ideas = expl.deep?["explore"]?["experiments"]?.list ?? []
                        if !ideas.isEmpty {
                            Text("Try this").font(.subheadline.weight(.semibold))
                            BulletList(items: ideas).font(.subheadline)
                        }
                        WarningsView(warnings: expl.quickMeta?.warnings)
                        AILabel(text: expl.label)
                    }
                    if let itemId = repo.itemId {
                        NavigationLink(value: Route.item(itemId)) {
                            Label("Full explanation (quick / technical / explore)", systemImage: "text.magnifyingglass")
                                .font(.subheadline.weight(.semibold))
                                .frame(maxWidth: .infinity, minHeight: 44)
                        }
                        .buttonStyle(.bordered)
                    }
                }
                if let releases = d.extras.releases, !releases.isEmpty {
                    SectionHeader(title: "Recent releases", icon: "shippingbox")
                    ForEach(releases) { rel in releaseRow(rel) }
                }
                if let readme = d.extras.readmeExcerpt, !readme.isEmpty {
                    ProvenanceBox(kind: .verified, title: "From the README", subtitle: "excerpt") {
                        Text(readme).font(.footnote).lineLimit(14).textSelection(.enabled)
                    }
                }
                if let topics = repo.topics, !topics.isEmpty {
                    SectionHeader(title: "GitHub topics", icon: "tag")
                    FlowText(items: topics)
                }
                if let spotted = repo.spottedOn, !spotted.isEmpty {
                    SectionHeader(title: "Discovered via", icon: "eye")
                    ForEach(spotted, id: \.self) { s in
                        if let link = s.link {
                            ExternalLinkButton(title: "Spotted on \(s.label ?? "trending page")", url: link)
                        }
                    }
                    Text("Trending sites are used only to discover repositories. All numbers here are AI Radar's own measurements via the GitHub API.")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                if let home = repo.homepage, !home.isEmpty, home.hasPrefix("http") {
                    ExternalLinkButton(title: "Project homepage", url: home)
                }
            }
            .padding()
        }
    }

    private func statsGrid(_ repo: RepoCard) -> some View {
        let columns = [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())]
        return LazyVGrid(columns: columns, spacing: 10) {
            stat("Stars", Formatting.count(repo.stars), "star.fill")
            stat("Forks", Formatting.count(repo.forks), "tuningfork")
            stat("Open issues", Formatting.count(repo.openIssues), "exclamationmark.circle")
            stat("Language", repo.language ?? "–", "curlybraces")
            stat("Created", Formatting.shortDate(repo.createdAt), "calendar")
            stat("Last push", Formatting.relative(iso: repo.pushedAt), "arrow.triangle.2.circlepath")
            stat("Latest release", repo.latestRelease?.tag ?? "none", "shippingbox")
            stat("License", repo.license ?? "–", "doc.plaintext")
            stat("Checked", Formatting.relative(iso: repo.lastCheckedAt), "clock")
        }
    }

    private func stat(_ title: String, _ value: String, _ icon: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(title, systemImage: icon).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.subheadline.weight(.semibold)).lineLimit(1).minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10).fill(Theme.cardBackground))
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder private func growthSection(_ repo: RepoCard, snapshots: [Snapshot]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Star growth", icon: "chart.line.uptrend.xyaxis")
            GrowthLine(repo: repo)
            let points = snapshots.compactMap { s -> (Date, Int)? in
                guard let d = s.date else { return nil }
                return (d, s.stars)
            }
            if points.count >= 2 {
                Chart {
                    ForEach(Array(points.enumerated()), id: \.offset) { _, p in
                        LineMark(x: .value("Time", p.0), y: .value("Stars", p.1))
                            .interpolationMethod(.monotone)
                        PointMark(x: .value("Time", p.0), y: .value("Stars", p.1))
                            .symbolSize(18)
                    }
                }
                .chartYScale(domain: .automatic(includesZero: false))
                .frame(height: 180)
                .foregroundStyle(Theme.accent)
                .accessibilityLabel("Star history chart with \(points.count) measurements")
                Text("\(points.count) measurements recorded by AI Radar since \(Formatting.date(snapshots.first?.t)).")
                    .font(.caption2).foregroundStyle(.secondary)
            } else {
                Text("A trend can't be calculated yet: AI Radar has \(points.count) measurement\(points.count == 1 ? "" : "s") of this repository. It measures tracked repositories every 6 hours; the chart appears after the second measurement.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: Theme.corner).fill(Theme.cardBackground))
    }

    private func releaseRow(_ rel: ReleaseInfo) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(rel.tag).font(.subheadline.weight(.semibold))
                if rel.prerelease == 1 {
                    Text("pre-release").font(.caption2).padding(4).background(Capsule().fill(Color.orange.opacity(0.2)))
                }
                Spacer()
                Text(Formatting.relative(iso: rel.publishedAt)).font(.caption).foregroundStyle(.secondary)
            }
            if let name = rel.name, name != rel.tag, !name.isEmpty {
                Text(name).font(.caption).foregroundStyle(.secondary)
            }
            if let body = rel.bodyExcerpt, !body.isEmpty {
                Text(body).font(.footnote).lineLimit(5).foregroundStyle(.secondary)
            }
            if let url = rel.url {
                ExternalLinkButton(title: "Release notes", url: url)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Theme.cardBackground))
    }
}

/// Simple wrapping row of small tags.
struct FlowText: View {
    let items: [String]
    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack { ForEach(items, id: \.self) { tag($0) } }
            VStack(alignment: .leading, spacing: 6) {
                ForEach(chunks(), id: \.self) { row in
                    HStack { ForEach(row, id: \.self) { tag($0) } }
                }
            }
        }
    }

    private func tag(_ s: String) -> some View {
        Text(s).font(.caption).padding(.horizontal, 8).padding(.vertical, 4)
            .background(Capsule().fill(Color.secondary.opacity(0.15)))
    }

    private func chunks() -> [[String]] {
        stride(from: 0, to: items.count, by: 3).map { Array(items[$0..<min($0 + 3, items.count)]) }
    }
}
