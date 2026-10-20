import SwiftUI

struct SavedScreen: View {
    @EnvironmentObject private var bookmarks: BookmarkStore
    @State private var search = ""
    @State private var filter: String = "All"

    private var categories: [String] {
        ["All"] + Array(Set(bookmarks.entries.map(\.categoryTitle))).sorted()
    }

    private var visible: [SavedEntry] {
        bookmarks.entries.filter { entry in
            (filter == "All" || entry.categoryTitle == filter) &&
                (search.isEmpty || entry.title.localizedCaseInsensitiveContains(search) ||
                    (entry.summary ?? "").localizedCaseInsensitiveContains(search))
        }
    }

    var body: some View {
        Group {
            if bookmarks.entries.isEmpty {
                EmptyStateView(icon: "bookmark", title: "Nothing saved yet",
                               message: "Tap the bookmark icon on any story, paper or repository to keep it here. Saved items stay on this iPhone, even offline.")
            } else {
                List {
                    if categories.count > 2 {
                        Picker("Type", selection: $filter) {
                            ForEach(categories, id: \.self) { Text($0).tag($0) }
                        }
                        .pickerStyle(.menu)
                    }
                    ForEach(visible) { entry in
                        NavigationLink(value: entry.kind == .repo ? Route.repo(entry.id.replacingOccurrences(of: "/", with: "__")) : Route.item(entry.id)) {
                            SavedRow(entry: entry)
                        }
                        .swipeActions {
                            Button(role: .destructive) {
                                bookmarks.remove(id: entry.id)
                            } label: {
                                Label("Remove", systemImage: "trash")
                            }
                        }
                    }
                    .onDelete { offsets in bookmarks.remove(atOffsets: offsets, in: visible) }
                }
                .listStyle(.insetGrouped)
            }
        }
        .navigationTitle("Saved")
        .searchable(text: $search, prompt: "Search saved items")
    }
}

struct SavedRow: View {
    let entry: SavedEntry
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: Theme.kindIcon(entry.itemKind)).foregroundStyle(Theme.accent)
                Text(entry.source ?? "").font(.caption.weight(.semibold))
                Text("· saved \(Formatting.relative(entry.savedAt))").font(.caption).foregroundStyle(.secondary)
            }
            Text(entry.title).font(.subheadline.weight(.semibold)).lineLimit(3)
            if let s = entry.summary, !s.isEmpty {
                Text(s).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }
        }
        .padding(.vertical, 4)
    }
}
