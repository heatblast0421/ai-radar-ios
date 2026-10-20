import SwiftUI

/// Home / AI Pulse: daily briefing + unified feed with For You / Latest / Trending.
struct PulseScreen: View {
    @StateObject private var model = FeedViewModel(section: "pulse", sort: .forYou)
    @EnvironmentObject private var app: AppModel
    @State private var search = ""

    var body: some View {
        FeedList(model: model, search: search, topics: TopicNames.order.filter { $0 != "research" },
                 sorts: [.forYou, .latest, .trending],
                 emptyMessage: "The radar hasn't collected anything yet. New items arrive every 15 minutes.",
                 onRefresh: { await app.refresh() }) {
            if search.isEmpty && model.topic == nil {
                BriefingCard()
                    .padding(.horizontal)
            }
        }
        .navigationTitle("AI Pulse")
        .searchable(text: $search, prompt: "Filter the feed")
        .toolbar { MainToolbar() }
    }
}

struct BriefingCard: View {
    @EnvironmentObject private var app: AppModel
    @State private var expanded = false

    var body: some View {
        if let b = app.briefing, b.available {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Label("Today's briefing", systemImage: "sun.horizon")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.accent)
                    Spacer()
                    if let day = b.day { Text(day).font(.caption).foregroundStyle(.secondary) }
                }
                if let headline = b.headline {
                    Text(headline).font(.title3.weight(.bold)).fixedSize(horizontal: false, vertical: true)
                }
                if let overview = b.overview, !overview.isEmpty {
                    Text(overview).font(.subheadline).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                let bullets = b.bullets ?? []
                ForEach(Array(bullets.prefix(expanded ? bullets.count : 3).enumerated()), id: \.offset) { _, bullet in
                    if let first = bullet.itemIds?.first {
                        NavigationLink(value: Route.item(first)) {
                            bulletRow(bullet.text, linked: true)
                        }
                        .buttonStyle(.plain)
                    } else {
                        bulletRow(bullet.text, linked: false)
                    }
                }
                if bullets.count > 3 {
                    Button(expanded ? "Show less" : "Show all \(bullets.count)") {
                        withAnimation { expanded.toggle() }
                    }
                    .font(.footnote.weight(.semibold))
                    .frame(minHeight: 44)
                }
                if let watch = b.watchNext, !watch.isEmpty, expanded {
                    Text("Worth watching").font(.footnote.weight(.semibold))
                    BulletList(items: watch)
                        .font(.footnote)
                }
                if let label = b.label {
                    Label(label, systemImage: b.kind == "ai" ? "sparkles" : "list.number")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: Theme.corner)
                    .fill(LinearGradient(colors: [Theme.accent.opacity(0.18), Theme.cardBackground],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
            )
            .overlay(RoundedRectangle(cornerRadius: Theme.corner).stroke(Theme.accent.opacity(0.3), lineWidth: 1))
        }
    }

    private func bulletRow(_ text: String, linked: Bool) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: "circle.fill").font(.system(size: 6)).foregroundStyle(Theme.accent)
            Text(text).font(.subheadline).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            if linked {
                Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
            }
        }
        .contentShape(Rectangle())
    }
}
