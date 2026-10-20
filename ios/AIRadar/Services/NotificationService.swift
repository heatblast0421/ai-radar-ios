import BackgroundTasks
import Foundation
import UserNotifications

/// Local notifications (no push server or paid Apple account needed):
/// - Daily briefing reminder at a time you choose (reliable, scheduled by iOS).
/// - "Important news" alerts, checked during background refresh. iOS decides when background refresh
///   runs (usually a few times a day, more often if you open the app regularly), so these are best-effort.
enum NotificationService {
    static let briefingId = "airadar.daily-briefing"
    static let refreshTaskId = "com.airadar.app.refresh"
    private static let seenKey = "alertedItemIds"
    private static let baselineKey = "alertsBaselineAt"

    static func authorizationStatus() async -> UNAuthorizationStatus {
        await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    @discardableResult
    static func requestPermission() async -> Bool {
        (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    static func scheduleDailyBriefing(hour: Int, minute: Int) {
        let content = UNMutableNotificationContent()
        content.title = "Your AI briefing is ready"
        content.body = "The most important AI developments from the last day, ranked and explained."
        content.sound = .default
        content.userInfo = ["open": "briefing"]
        var comps = DateComponents()
        comps.hour = hour
        comps.minute = minute
        let trigger = UNCalendarNotificationTrigger(dateMatching: comps, repeats: true)
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [briefingId])
        center.add(UNNotificationRequest(identifier: briefingId, content: content, trigger: trigger))
    }

    static func cancelDailyBriefing() {
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [briefingId])
    }

    // MARK: Background refresh

    static func scheduleBackgroundRefresh() {
        let request = BGAppRefreshTaskRequest(identifier: refreshTaskId)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 60 * 60)
        try? BGTaskScheduler.shared.submit(request)
    }

    /// Fetches the Pulse feed (also warming the offline cache) and alerts about new high-importance items.
    static func performBackgroundRefresh() async {
        let defaults = UserDefaults.standard
        guard defaults.object(forKey: Preferences.Keys.backgroundRefresh) as? Bool ?? true else { return }
        scheduleBackgroundRefresh()
        guard let page = try? await APIClient.shared.get("feed/pulse/top/1.json", as: FeedPage.self, allowStale: false) else { return }
        _ = try? await APIClient.shared.get("briefing.json", as: Briefing.self, allowStale: false)
        let notify = defaults.object(forKey: Preferences.Keys.notifyBreaking) as? Bool ?? false
        let followed = Set(defaults.array(forKey: Preferences.Keys.followedTopics) as? [String] ?? Array(Preferences.defaultTopics))
        let fresh = newImportantItems(in: page.value.items, followed: followed)
        guard notify, await authorizationStatus() == .authorized else { return }
        for card in fresh.prefix(2) {
            let content = UNMutableNotificationContent()
            content.title = card.title
            content.subtitle = card.source.name
            content.body = card.summary ?? ""
            content.sound = .default
            content.userInfo = ["itemId": card.id]
            try? await UNUserNotificationCenter.current().add(
                UNNotificationRequest(identifier: "item-\(card.id)", content: content, trigger: nil))
        }
    }

    /// High-importance items discovered after the last check that match followed topics. The first check
    /// only records a baseline, so installing the app doesn't trigger a burst of old alerts.
    static func newImportantItems(in cards: [FeedCard], followed: Set<String>, defaults: UserDefaults = .standard) -> [FeedCard] {
        var seen = Set(defaults.array(forKey: seenKey) as? [String] ?? [])
        let baseline = defaults.object(forKey: baselineKey) as? Date
        let candidates = cards.filter { card in
            card.importance == "high" && !seen.contains(card.id) &&
                (followed.isEmpty || card.topics.contains(where: followed.contains))
        }
        let result: [FeedCard]
        if let baseline {
            result = candidates.filter { ($0.discoveredDate ?? .distantPast) > baseline }
        } else {
            result = []
        }
        for c in cards where c.importance == "high" { seen.insert(c.id) }
        defaults.set(Array(seen.suffix(500)), forKey: seenKey)
        defaults.set(Date(), forKey: baselineKey)
        return result
    }
}
