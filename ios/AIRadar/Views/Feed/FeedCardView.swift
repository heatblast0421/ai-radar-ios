import SwiftUI

struct FeedCardView: View {
    let card: FeedCard
    @EnvironmentObject private var bookmarks: BookmarkStore

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: Theme.kindIcon(card.kind))
                    .foregroundStyle(Theme.accent)
                Text(card.source.name)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                if card.source.official == true {
                    Image(systemName: "checkmark.seal.fill")
                        .font(.caption2)
                        .foregroundStyle(.green)
                        .accessibilityLabel("Official source")
                }
                Text("· \(Formatting.relative(card.publishedDate))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer(minLength: 4)
                ImportanceBadge(importance: card.importance, reason: card.importanceReason)
            }

            Text(card.title)
                .font(.headline)
                .foregroundStyle(.primary)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)

            if let summary = card.summary, !summary.isEmpty {
                HStack(alignment: .top, spacing: 6) {
                    if card.isAISummary {
                        Image(systemName: "sparkles")
                            .font(.caption)
                            .foregroundStyle(.purple)
                            .accessibilityLabel("AI summary")
                    }
                    Text(summary)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(4)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            metricsRow

            HStack(alignment: .center) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(card.topics.prefix(3), id: \.self) { TopicChip(topic: $0) }
                    }
                }
                Button {
                    bookmarks.toggle(SavedEntry(card: card))
                } label: {
                    Image(systemName: bookmarks.isSaved(card.id) ? "bookmark.fill" : "bookmark")
                        .font(.body)
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .foregroundStyle(bookmarks.isSaved(card.id) ? Theme.accent : .secondary)
                .accessibilityLabel(bookmarks.isSaved(card.id) ? "Remove bookmark" : "Bookmark")
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: Theme.corner).fill(Theme.cardBackground))
        .contentShape(RoundedRectangle(cornerRadius: Theme.corner))
    }

    @ViewBuilder private var metricsRow: some View {
        let m = card.metrics
        let pieces: [(String, String)] = [
            m?.hnPoints.map { ("arrow.up", "\($0) pts") },
            m?.hnComments.map { ("bubble.left", "\($0)") },
            m?.hfUpvotes.map { ("hand.thumbsup", "\($0) upvotes") },
            m?.hfLikes.map { ("heart", Formatting.count($0)) },
            m?.stars.map { ("star", Formatting.count($0)) },
        ].compactMap { $0 }
        let others = card.supporting?.count ?? 0
        if !pieces.isEmpty || others > 0 {
            HStack(spacing: 12) {
                ForEach(Array(pieces.enumerated()), id: \.offset) { _, p in
                    Label(p.1, systemImage: p.0)
                }
                if others > 0 {
                    Label("+\(others) source\(others == 1 ? "" : "s")", systemImage: "square.stack.3d.up")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .labelStyle(.titleAndIcon)
        }
    }
}
