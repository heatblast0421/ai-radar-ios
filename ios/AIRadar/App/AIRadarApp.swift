import SwiftUI
import UserNotifications

@main
struct AIRadarApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var prefs = Preferences()
    @StateObject private var bookmarks = BookmarkStore()
    @StateObject private var app = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(prefs)
                .environmentObject(bookmarks)
                .environmentObject(app)
                .preferredColorScheme(prefs.appearance.colorScheme)
                .onAppear { appDelegate.appModel = app }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background && prefs.backgroundRefresh {
                NotificationService.scheduleBackgroundRefresh()
            }
            if phase == .active {
                Task { await app.refresh() }
            }
        }
        .backgroundTask(.appRefresh(NotificationService.refreshTaskId)) {
            await NotificationService.performBackgroundRefresh()
        }
    }
}

/// Handles taps on notifications (opens the item or the briefing).
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    weak var appModel: AppModel?

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let itemId = response.notification.request.content.userInfo["itemId"] as? String
        Task { @MainActor in
            if let itemId { self.appModel?.pendingItemId = itemId }
            completionHandler()
        }
    }
}
