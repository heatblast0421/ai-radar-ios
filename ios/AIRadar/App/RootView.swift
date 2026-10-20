import SwiftUI

enum Route: Hashable {
    case item(String)
    case repo(String)      // file id: owner__name
    case saved
    case settings
    case search
    case sources
}

enum AppTab: String, CaseIterable {
    case pulse, github, research, lab, industry
}

/// Toolbar shared by all tabs: search, saved, settings.
struct MainToolbar: ToolbarContent {
    var body: some ToolbarContent {
        ToolbarItemGroup(placement: .topBarTrailing) {
            NavigationLink(value: Route.search) {
                Image(systemName: "magnifyingglass")
            }
            .accessibilityLabel("Search everything")
            NavigationLink(value: Route.saved) {
                Image(systemName: "bookmark")
            }
            .accessibilityLabel("Saved")
            NavigationLink(value: Route.settings) {
                Image(systemName: "gearshape")
            }
            .accessibilityLabel("Settings")
        }
    }
}

struct RouteDestination: ViewModifier {
    func body(content: Content) -> some View {
        content.navigationDestination(for: Route.self) { route in
            switch route {
            case .item(let id): ItemDetailView(id: id)
            case .repo(let fileId): RepoDetailView(fileId: fileId)
            case .saved: SavedScreen()
            case .settings: SettingsScreen()
            case .search: SearchScreen()
            case .sources: SourcesStatusView()
            }
        }
    }
}

struct TabRoot<Content: View>: View {
    @Binding var path: NavigationPath
    @ViewBuilder let content: () -> Content

    var body: some View {
        NavigationStack(path: $path) {
            content().modifier(RouteDestination())
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var app: AppModel
    @EnvironmentObject private var prefs: Preferences
    @State private var tab: AppTab = RootView.initialTab()
    @State private var paths: [AppTab: NavigationPath] = [:]

    var body: some View {
        TabView(selection: $tab) {
            TabRoot(path: binding(.pulse)) { PulseScreen() }
                .tabItem { Label("Pulse", systemImage: "dot.radiowaves.left.and.right") }
                .tag(AppTab.pulse)
            TabRoot(path: binding(.github)) { GitHubRadarScreen() }
                .tabItem { Label("GitHub", systemImage: "chevron.left.forwardslash.chevron.right") }
                .tag(AppTab.github)
            TabRoot(path: binding(.research)) {
                FeedScreen(title: "Models & Research", section: "research",
                           topics: ["models", "agents", "rag", "memory", "evals", "inference", "training", "multimodal", "safety"],
                           emptyMessage: "Model releases, papers and benchmarks will appear here.")
            }
            .tabItem { Label("Research", systemImage: "brain") }
            .tag(AppTab.research)
            TabRoot(path: binding(.lab)) {
                FeedScreen(title: "Engineering Lab", section: "lab",
                           topics: ["agents", "mcp", "rag", "memory", "evals", "inference", "infra", "devtools", "safety"],
                           emptyMessage: "Agent frameworks, MCP, RAG, evals and inference news will appear here.")
            }
            .tabItem { Label("Lab", systemImage: "flask") }
            .tag(AppTab.lab)
            TabRoot(path: binding(.industry)) {
                FeedScreen(title: "AI Industry", section: "industry",
                           topics: ["industry", "agents", "models", "devtools", "safety", "infra"],
                           emptyMessage: "Startup launches, funding and industry changes will appear here.",
                           defaultSort: .latest)
            }
            .tabItem { Label("Industry", systemImage: "building.2") }
            .tag(AppTab.industry)
        }
        .tint(Theme.accent)
        .task { await app.refresh() }
        .onChange(of: app.pendingItemId) { _, newValue in
            guard let id = newValue else { return }
            tab = .pulse
            paths[.pulse, default: NavigationPath()].append(Route.item(id))
            app.pendingItemId = nil
        }
        .onAppear(perform: openScreenForScreenshots)
    }

    private func binding(_ tab: AppTab) -> Binding<NavigationPath> {
        Binding(get: { paths[tab] ?? NavigationPath() }, set: { paths[tab] = $0 })
    }

    /// Launch arguments used by automated UI screenshots, e.g. `-AIRadarStartTab github`.
    static func initialTab() -> AppTab {
        AppTab(rawValue: UserDefaults.standard.string(forKey: "AIRadarStartTab") ?? "") ?? .pulse
    }

    private func openScreenForScreenshots() {
        let defaults = UserDefaults.standard
        guard let screen = defaults.string(forKey: "AIRadarStartScreen") else { return }
        switch screen {
        case "settings": paths[tab, default: NavigationPath()].append(Route.settings)
        case "search": paths[tab, default: NavigationPath()].append(Route.search)
        case "saved": paths[tab, default: NavigationPath()].append(Route.saved)
        case "sources": paths[tab, default: NavigationPath()].append(Route.sources)
        default:
            if screen.hasPrefix("item:") {
                paths[tab, default: NavigationPath()].append(Route.item(String(screen.dropFirst(5))))
            } else if screen.hasPrefix("repo:") {
                paths[tab, default: NavigationPath()].append(Route.repo(String(screen.dropFirst(5))))
            }
        }
    }
}
