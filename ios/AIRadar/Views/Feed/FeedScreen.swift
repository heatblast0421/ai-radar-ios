import SwiftUI

/// A section feed (Models & Research, Engineering Lab, AI Industry) with sort, topic filters and search.
struct FeedScreen: View {
    let title: String
    let section: String
    let topics: [String]
    let emptyMessage: String

    @StateObject private var model: FeedViewModel
    @EnvironmentObject private var prefs: Preferences
    @EnvironmentObject private var bookmarks: BookmarkStore
    @State private var search = ""

    init(title: String, section: String, topics: [String], emptyMessage: String, defaultSort: FeedSort = .top) {
        self.title = title
        self.section = section
        self.topics = topics
        self.emptyMessage = emptyMessage
        _model = StateObject(wrappedValue: FeedViewModel(section: section, sort: defaultSort))
    }

    var body: some View {
        FeedList(model: model, search: search, topics: topics, sorts: [.top, .latest, .trending],
                 emptyMessage: emptyMessage, header: { EmptyView() })
            .navigationTitle(title)
            .searchable(text: $search, prompt: "Filter \(title)")
            .toolbar { MainToolbar() }
    }
}

/// Shared list body: sort picker, topic chips, cards, paging footer, loading/empty/error states.
struct FeedList<Header: View>: View {
    @ObservedObject var model: FeedViewModel
    let search: String
    let topics: [String]
    let sorts: [FeedSort]
    let emptyMessage: String
    var onRefresh: (() async -> Void)? = nil
    @ViewBuilder let header: () -> Header

    @EnvironmentObject private var prefs: Preferences
    @EnvironmentObject private var bookmarks: BookmarkStore

    var body: some View {
        let visible = model.visible(search: search, followed: prefs.followedTopics, affinity: bookmarks.topicAffinity)
        ScrollView {
            LazyVStack(spacing: 12, pinnedViews: []) {
                Picker("Sort", selection: Binding(get: { model.sort }, set: { newValue in
                    Task { await model.changeSort(newValue) }
                })) {
                    ForEach(sorts) { Text($0.title).tag($0) }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)

                TopicFilterBar(topics: topics, selection: $model.topic)

                if let stale = model.staleSince, model.phase == .loaded {
                    StaleBanner(fetchedAt: stale)
                }

                header()

                switch model.phase {
                case .idle, .loading:
                    LoadingView()
                case .failed(let message):
                    ErrorStateView(message: message) { Task { await model.reload() } }
                case .loaded:
                    if visible.isEmpty && !model.hasMore {
                        EmptyStateView(icon: "tray", title: "Nothing here yet",
                                       message: model.topic != nil || !search.isEmpty
                                           ? "No items match this filter. Try another topic or clear the search."
                                           : emptyMessage,
                                       actionTitle: model.topic != nil ? "Clear topic filter" : nil,
                                       action: model.topic != nil ? { model.topic = nil } : nil)
                    } else {
                        ForEach(visible) { card in
                            NavigationLink(value: Route.item(card.id)) {
                                FeedCardView(card: card)
                            }
                            .buttonStyle(.plain)
                            .padding(.horizontal)
                        }
                        footer(visibleCount: visible.count)
                    }
                }
            }
            .padding(.vertical, 8)
        }
        .background(Theme.screenBackground)
        .refreshable {
            await onRefresh?()
            await model.reload()
        }
        .task { await model.loadIfNeeded() }
    }

    @ViewBuilder private func footer(visibleCount: Int) -> some View {
        if model.hasMore {
            HStack {
                Spacer()
                if model.isLoadingMore {
                    ProgressView()
                } else {
                    Button("Load more") { Task { await model.loadMore() } }
                        .frame(minHeight: 44)
                }
                Spacer()
            }
            .padding(.vertical, 12)
            .task(id: model.cards.count) {
                // Infinite scroll. Re-runs after each page, so with a topic filter active it keeps
                // fetching while the footer is still on screen (i.e. until enough matches appear).
                await model.loadMore()
            }
        } else if model.total > 0 {
            Text("You're all caught up · \(model.total) items")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .padding(.vertical, 16)
        }
    }
}
