import SwiftUI

enum Theme {
    static let accent = Color("AccentColor")
    static let cardBackground = Color(uiColor: .secondarySystemGroupedBackground)
    static let screenBackground = Color(uiColor: .systemGroupedBackground)
    static let subtle = Color.secondary.opacity(0.8)
    static let corner: CGFloat = 14

    static func kindIcon(_ kind: String) -> String {
        switch kind {
        case "paper": return "doc.text.magnifyingglass"
        case "repo": return "chevron.left.forwardslash.chevron.right"
        case "release": return "shippingbox"
        case "model": return "cpu"
        case "discussion": return "bubble.left.and.bubble.right"
        default: return "newspaper"
        }
    }

    static func kindLabel(_ kind: String) -> String {
        switch kind {
        case "paper": return "Paper"
        case "repo": return "Repository"
        case "release": return "Release"
        case "model": return "Model"
        case "discussion": return "Discussion"
        default: return "Article"
        }
    }

    static func topicColor(_ topic: String) -> Color {
        switch topic {
        case "agents": return .teal
        case "mcp": return .cyan
        case "rag": return .indigo
        case "memory": return .purple
        case "evals": return .orange
        case "inference": return .green
        case "infra": return .mint
        case "training": return .brown
        case "models": return .blue
        case "multimodal": return .pink
        case "devtools": return .yellow
        case "safety": return .red
        case "industry": return .gray
        default: return .secondary
        }
    }
}

/// Human topic names (fallback when meta.json hasn't loaded yet).
enum TopicNames {
    static let fallback: [String: String] = [
        "agents": "Agents", "mcp": "MCP & Tools", "rag": "RAG & Retrieval", "memory": "Memory & Context",
        "evals": "Evals & Observability", "inference": "Inference & Optimization", "infra": "AI Infrastructure",
        "training": "Training & Fine-tuning", "models": "Models & APIs", "multimodal": "Multimodal",
        "devtools": "Developer Tools", "safety": "Safety & Security", "research": "Research", "industry": "Industry",
    ]
    static let order = ["agents", "mcp", "rag", "memory", "evals", "inference", "infra", "models", "training",
                        "multimodal", "devtools", "safety", "research", "industry"]

    static func name(_ id: String) -> String { fallback[id] ?? id.capitalized }
}

enum Formatting {
    private static let relativeFormatter: RelativeDateTimeFormatter = {
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .abbreviated
        return f
    }()

    static func relative(_ date: Date?) -> String {
        guard let date else { return "" }
        if abs(date.timeIntervalSinceNow) < 60 { return "just now" }
        return relativeFormatter.localizedString(for: date, relativeTo: Date())
    }

    static func relative(iso: String?) -> String {
        relative(DateParsing.parse(iso))
    }

    static func date(_ iso: String?) -> String {
        guard let d = DateParsing.parse(iso) else { return "unknown" }
        return d.formatted(date: .abbreviated, time: .shortened)
    }

    static func shortDate(_ iso: String?) -> String {
        guard let d = DateParsing.parse(iso) else { return "unknown" }
        return d.formatted(date: .abbreviated, time: .omitted)
    }

    static func count(_ n: Int?) -> String {
        guard let n else { return "–" }
        if n >= 1_000_000 { return String(format: "%.1fM", Double(n) / 1_000_000) }
        if n >= 10_000 { return String(format: "%.0fk", Double(n) / 1_000) }
        if n >= 1_000 { return String(format: "%.1fk", Double(n) / 1_000) }
        return "\(n)"
    }

    static func signed(_ n: Int) -> String { n >= 0 ? "+\(count(n))" : "-\(count(-n))" }

    static func perDay(_ value: Double) -> String {
        value >= 10 ? String(format: "%.0f", value) : String(format: "%.1f", value)
    }
}
