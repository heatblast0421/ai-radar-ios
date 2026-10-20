import SwiftUI

struct TopicChip: View {
    let topic: String
    var selected: Bool = false

    var body: some View {
        Text(TopicNames.name(topic))
            .font(.caption.weight(.medium))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .foregroundStyle(selected ? Color.black : Theme.topicColor(topic))
            .background(
                Capsule().fill(selected ? Theme.topicColor(topic) : Theme.topicColor(topic).opacity(0.14))
            )
            .accessibilityLabel("Topic \(TopicNames.name(topic))")
    }
}

/// Horizontally scrolling filter chips. `nil` selection means "All".
struct TopicFilterBar: View {
    let topics: [String]
    @Binding var selection: String?

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                Button {
                    selection = nil
                } label: {
                    Text("All")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .foregroundStyle(selection == nil ? Color.black : Color.primary)
                        .background(Capsule().fill(selection == nil ? Theme.accent : Color.secondary.opacity(0.15)))
                }
                .buttonStyle(.plain)
                ForEach(topics, id: \.self) { topic in
                    Button {
                        selection = selection == topic ? nil : topic
                    } label: {
                        TopicChip(topic: topic, selected: selection == topic)
                            .padding(.vertical, 2)
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(selection == topic ? .isSelected : [])
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 6)
        }
    }
}

struct ImportanceBadge: View {
    let importance: String?
    let reason: String?

    var body: some View {
        if let importance {
            Label(importance == "high" ? "Important" : "Notable",
                  systemImage: importance == "high" ? "flame.fill" : "sparkles")
                .font(.caption2.weight(.bold))
                .padding(.horizontal, 6)
                .padding(.vertical, 3)
                .foregroundStyle(importance == "high" ? Color.orange : Color.yellow)
                .background(Capsule().fill((importance == "high" ? Color.orange : Color.yellow).opacity(0.15)))
                .accessibilityLabel("\(importance == "high" ? "Important" : "Notable")\(reason.map { ", \($0)" } ?? "")")
        }
    }
}

struct StaleBanner: View {
    let fetchedAt: Date

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "wifi.slash")
            Text("Offline: showing the copy saved \(Formatting.relative(fetchedAt)). Pull down to retry.")
                .font(.footnote)
        }
        .foregroundStyle(.orange)
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.orange.opacity(0.12)))
        .padding(.horizontal)
    }
}

struct LoadingView: View {
    var message: String = "Loading the latest AI developments…"
    var body: some View {
        VStack(spacing: 14) {
            ProgressView()
                .controlSize(.large)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, minHeight: 280)
        .padding()
    }
}

struct ErrorStateView: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 40))
                .foregroundStyle(.orange)
            Text("Couldn't load")
                .font(.headline)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button(action: retry) {
                Label("Try again", systemImage: "arrow.clockwise")
                    .frame(minWidth: 140, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, minHeight: 280)
        .padding()
    }
}

struct EmptyStateView: View {
    let icon: String
    let title: String
    let message: String
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 40))
                .foregroundStyle(.secondary)
            Text(title).font(.headline)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(.bordered)
                    .frame(minHeight: 44)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 240)
        .padding()
    }
}

/// A labelled box separating verified source content from AI interpretation.
struct ProvenanceBox<Content: View>: View {
    enum Kind { case verified, ai, info }
    let kind: Kind
    let title: String
    var subtitle: String?
    @ViewBuilder let content: Content

    private var color: Color {
        switch kind {
        case .verified: return .green
        case .ai: return .purple
        case .info: return .blue
        }
    }

    private var icon: String {
        switch kind {
        case .verified: return "checkmark.seal"
        case .ai: return "sparkles"
        case .info: return "info.circle"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Label(title, systemImage: icon)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(color)
                Spacer()
                if let subtitle {
                    Text(subtitle).font(.caption2).foregroundStyle(.secondary)
                }
            }
            content
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Theme.corner).fill(color.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: Theme.corner).stroke(color.opacity(0.25), lineWidth: 1))
    }
}

struct SectionHeader: View {
    let title: String
    var icon: String?
    var body: some View {
        HStack(spacing: 6) {
            if let icon { Image(systemName: icon) }
            Text(title)
        }
        .font(.headline)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, 6)
    }
}

struct BulletList: View {
    let items: [String]
    var symbol: String = "circle.fill"
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, text in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: symbol)
                        .font(.system(size: 5))
                        .foregroundStyle(.secondary)
                        .offset(y: -2)
                    Text(text).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

/// Opens links in Safari via the system; used for "Open source" style buttons.
struct ExternalLinkButton: View {
    let title: String
    let url: String
    var icon: String = "arrow.up.right.square"

    var body: some View {
        if let link = URL(string: url) {
            Link(destination: link) {
                Label(title, systemImage: icon)
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.bordered)
        }
    }
}
