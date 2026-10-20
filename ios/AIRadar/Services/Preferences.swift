import SwiftUI

/// User settings, stored on the device (UserDefaults). Nothing here leaves the phone.
@MainActor
final class Preferences: ObservableObject {
    enum Keys {
        static let followedTopics = "followedTopics"
        static let summaryLevel = "summaryLevel"
        static let appearance = "appearance"
        static let notifyBreaking = "notifyBreaking"
        static let notifyBriefing = "notifyBriefing"
        static let briefingHour = "briefingHour"
        static let briefingMinute = "briefingMinute"
        static let backgroundRefresh = "backgroundRefresh"
        static let apiBaseOverride = "apiBaseOverride"
        static let hideSeenInLatest = "hideSeenInLatest"
    }

    /// Topics followed by default (practical AI engineering focus).
    static let defaultTopics: Set<String> = ["agents", "mcp", "rag", "memory", "evals", "inference", "infra", "models", "devtools"]

    private let defaults: UserDefaults

    @Published var followedTopics: Set<String> { didSet { defaults.set(Array(followedTopics).sorted(), forKey: Keys.followedTopics) } }
    @Published var summaryLevel: SummaryLevel { didSet { defaults.set(summaryLevel.rawValue, forKey: Keys.summaryLevel) } }
    @Published var appearance: Appearance { didSet { defaults.set(appearance.rawValue, forKey: Keys.appearance) } }
    @Published var notifyBreaking: Bool { didSet { defaults.set(notifyBreaking, forKey: Keys.notifyBreaking) } }
    @Published var notifyBriefing: Bool { didSet { defaults.set(notifyBriefing, forKey: Keys.notifyBriefing) } }
    @Published var briefingHour: Int { didSet { defaults.set(briefingHour, forKey: Keys.briefingHour) } }
    @Published var briefingMinute: Int { didSet { defaults.set(briefingMinute, forKey: Keys.briefingMinute) } }
    @Published var backgroundRefresh: Bool { didSet { defaults.set(backgroundRefresh, forKey: Keys.backgroundRefresh) } }
    @Published var apiBaseOverride: String { didSet { defaults.set(apiBaseOverride, forKey: Keys.apiBaseOverride) } }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let saved = defaults.array(forKey: Keys.followedTopics) as? [String] {
            followedTopics = Set(saved)
        } else {
            followedTopics = Preferences.defaultTopics
        }
        summaryLevel = SummaryLevel(rawValue: defaults.string(forKey: Keys.summaryLevel) ?? "") ?? .quick
        appearance = Appearance(rawValue: defaults.string(forKey: Keys.appearance) ?? "") ?? .dark
        notifyBreaking = defaults.object(forKey: Keys.notifyBreaking) as? Bool ?? false
        notifyBriefing = defaults.object(forKey: Keys.notifyBriefing) as? Bool ?? false
        briefingHour = defaults.object(forKey: Keys.briefingHour) as? Int ?? 8
        briefingMinute = defaults.object(forKey: Keys.briefingMinute) as? Int ?? 0
        backgroundRefresh = defaults.object(forKey: Keys.backgroundRefresh) as? Bool ?? true
        apiBaseOverride = defaults.string(forKey: Keys.apiBaseOverride) ?? ""
    }

    func toggle(topic: String) {
        if followedTopics.contains(topic) {
            followedTopics.remove(topic)
        } else {
            followedTopics.insert(topic)
        }
    }

    var briefingTime: Date {
        get {
            Calendar.current.date(bySettingHour: briefingHour, minute: briefingMinute, second: 0, of: Date()) ?? Date()
        }
        set {
            let comps = Calendar.current.dateComponents([.hour, .minute], from: newValue)
            briefingHour = comps.hour ?? 8
            briefingMinute = comps.minute ?? 0
        }
    }
}

enum SummaryLevel: String, CaseIterable, Identifiable {
    case quick, technical, explore
    var id: String { rawValue }
    var title: String {
        switch self {
        case .quick: return "Quick"
        case .technical: return "Technical"
        case .explore: return "Explore"
        }
    }
    var explanation: String {
        switch self {
        case .quick: return "A 20-second summary first"
        case .technical: return "Open items on the technical deep-dive"
        case .explore: return "Open items on experiments and next steps"
        }
    }
}

enum Appearance: String, CaseIterable, Identifiable {
    case system, dark, light
    var id: String { rawValue }
    var title: String { rawValue.capitalized }
    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .dark: return .dark
        case .light: return .light
        }
    }
}
