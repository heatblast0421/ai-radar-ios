import SwiftUI

struct GitHubRadarScreen: View {
    @StateObject private var model = RepoListViewModel()
    @State private var search = ""
    private let categories = ["agents", "mcp", "rag", "memory", "models", "inference", "evals", "infra", "training", "devtools", "multimodal"]

    var body: some View {
        let visible = model.visible(search: search)
        ScrollView {
            LazyVStack(spacing: 12) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(RepoSort.allCases) { sort in
                            Button {
                                Task { await model.changeSort(sort) }
                            } label: {
                                Text(sort.title)
                                    .font(.subheadline.weight(.semibold))
                                    .padding(.horizontal, 12)
                                    .frame(minHeight: 36)
                                    .foregroundStyle(model.sort == sort ? Color.black : Color.primary)
                                    .background(Capsule().fill(model.sort == sort ? Theme.accent : Color.secondary.opacity(0.15)))
                            }
                            .buttonStyle(.plain)
                            .accessibilityAddTraits(model.sort == sort ? .isSelected : [])
                        }
                    }
                    .padding(.horizontal)
                }
                TopicFilterBar(topics: categories, selection: $model.category)

                if let description = model.sortDescription {
                    Text(description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal)
                }
                if let stale = model.staleSince, model.phase == .loaded { StaleBanner(fetchedAt: stale) }

                switch model.phase {
                case .idle, .loading:
                    LoadingView(message: "Scanning GitHub…")
                case .failed(let message):
                    ErrorStateView(message: message) { Task { await model.reload() } }
                case .loaded:
                    if visible.isEmpty && !model.hasMore {
                        EmptyStateView(
                            icon: model.sort == .growing ? "chart.line.uptrend.xyaxis" : "magnifyingglass",
                            title: model.sort == .growing ? "Collecting growth data" : "No repositories",
                            message: model.sort == .growing
                                ? "AI Radar measures stars every 6 hours. Growth appears here once a repository has been measured at least twice. Nothing is estimated."
                                : "Nothing matches this filter yet.",
                            actionTitle: model.category != nil ? "Clear filter" : nil,
                            action: model.category != nil ? { model.category = nil } : nil)
                    } else {
                        ForEach(visible) { repo in
                            NavigationLink(value: Route.repo(repo.fileId)) {
                                RepoRowView(repo: repo)
                            }
                            .buttonStyle(.plain)
                            .padding(.horizontal)
                        }
                        if model.hasMore {
                            HStack {
                                Spacer()
                                if model.isLoadingMore { ProgressView() } else {
                                    Button("Load more") { Task { await model.loadMore() } }.frame(minHeight: 44)
                                }
                                Spacer()
                            }
                            .padding(.vertical, 12)
                            .task(id: model.repos.count) { await model.loadMore() }
                        } else {
                            Text("\(model.total) repositories")
                                .font(.footnote).foregroundStyle(.secondary).padding(.vertical, 16)
                        }
                    }
                }
            }
            .padding(.vertical, 8)
        }
        .background(Theme.screenBackground)
        .navigationTitle("GitHub Radar")
        .searchable(text: $search, prompt: "Filter repositories")
        .toolbar { MainToolbar() }
        .refreshable { await model.reload() }
        .task { await model.loadIfNeeded() }
    }
}

struct RepoRowView: View {
    let repo: RepoCard
    @EnvironmentObject private var bookmarks: BookmarkStore

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(repo.owner).font(.caption).foregroundStyle(.secondary)
                    Text(repo.name).font(.headline)
                }
                Spacer()
                Button {
                    bookmarks.toggle(SavedEntry(repo: repo))
                } label: {
                    Image(systemName: bookmarks.isSaved(repo.id) ? "bookmark.fill" : "bookmark")
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .foregroundStyle(bookmarks.isSaved(repo.id) ? Theme.accent : .secondary)
                .accessibilityLabel(bookmarks.isSaved(repo.id) ? "Remove bookmark" : "Bookmark")
            }
            if let text = repo.aiSummary ?? repo.description {
                Text(text).font(.subheadline).foregroundStyle(.secondary).lineLimit(3)
            }
            HStack(spacing: 12) {
                Label(Formatting.count(repo.stars), systemImage: "star.fill").foregroundStyle(.yellow)
                Label(Formatting.count(repo.forks), systemImage: "tuningfork")
                if let lang = repo.language { Label(lang, systemImage: "curlybraces") }
                Spacer(minLength: 0)
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            GrowthLine(repo: repo)
            HStack(spacing: 10) {
                if let created = repo.createdAt {
                    Text("Created \(Formatting.relative(iso: created))")
                }
                if let pushed = repo.pushedAt {
                    Text("· Updated \(Formatting.relative(iso: pushed))")
                }
                if let tag = repo.latestRelease?.tag {
                    Text("· \(tag)").lineLimit(1)
                }
            }
            .font(.caption2)
            .foregroundStyle(.secondary)
            if let spotted = repo.spottedOn, !spotted.isEmpty {
                HStack(spacing: 6) {
                    ForEach(spotted.compactMap(\.label), id: \.self) { label in
                        Label("Spotted on \(label)", systemImage: "eye")
                            .font(.caption2)
                            .padding(.horizontal, 6).padding(.vertical, 3)
                            .background(Capsule().fill(Color.secondary.opacity(0.12)))
                    }
                }
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: Theme.corner).fill(Theme.cardBackground))
        .contentShape(RoundedRectangle(cornerRadius: Theme.corner))
    }
}

/// Growth summary that never invents numbers: measured values when we have ≥2 snapshots,
/// otherwise a clear "collecting data" note plus GitHub's own creation-date average.
struct GrowthLine: View {
    let repo: RepoCard

    var body: some View {
        let g = repo.growth
        HStack(spacing: 6) {
            if g?.trendAvailable == true {
                Image(systemName: "chart.line.uptrend.xyaxis").foregroundStyle(.green)
                Text(measuredText(g)).foregroundStyle(.green)
            } else {
                Image(systemName: "hourglass").foregroundStyle(.secondary)
                Text(collectingText(g)).foregroundStyle(.secondary)
            }
        }
        .font(.caption.weight(.medium))
        .lineLimit(2)
    }

    private func measuredText(_ g: RepoGrowth?) -> String {
        guard let g else { return "" }
        if let week = g.starsWeek { return "\(Formatting.signed(week)) stars in 7 days (measured)" }
        if let day = g.starsDay { return "\(Formatting.signed(day)) stars in 24h (measured)" }
        if let rate = g.starsPerDayMeasured, let hours = g.measuredWindowHours {
            return "≈\(Formatting.perDay(rate)) stars/day, measured over \(Int(hours))h"
        }
        return "Trend available"
    }

    private func collectingText(_ g: RepoGrowth?) -> String {
        var text = "Trend: collecting data"
        if let since = g?.trackingSince { text += " (tracking started \(Formatting.relative(iso: since)))" }
        if let avg = g?.avgStarsPerDaySinceCreation, avg > 0 {
            text += " · avg \(Formatting.perDay(avg))★/day since creation"
        }
        return text
    }
}
