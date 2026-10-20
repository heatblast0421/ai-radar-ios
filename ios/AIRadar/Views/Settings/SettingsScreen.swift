import SwiftUI
import UserNotifications

struct SettingsScreen: View {
    @EnvironmentObject private var prefs: Preferences
    @EnvironmentObject private var app: AppModel
    @EnvironmentObject private var bookmarks: BookmarkStore
    @State private var notificationStatus: UNAuthorizationStatus = .notDetermined
    @State private var cacheSize = ""
    @State private var showCacheCleared = false
    @State private var editingBackend = false
    @State private var backendDraft = ""

    var body: some View {
        Form {
            topicsSection
            readingSection
            notificationsSection
            refreshSection
            appearanceSection
            statusSection
            aboutSection
        }
        .navigationTitle("Settings")
        .task {
            notificationStatus = await NotificationService.authorizationStatus()
            cacheSize = APIClient.shared.cache.sizeDescription
            await app.loadMeta()
        }
    }

    // MARK: Topics

    private var topicsSection: some View {
        Section {
            ForEach(app.topics) { topic in
                Toggle(isOn: Binding(get: { prefs.followedTopics.contains(topic.id) },
                                     set: { _ in prefs.toggle(topic: topic.id) })) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(topic.name)
                        if let d = topic.description {
                            Text(d).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .tint(Theme.topicColor(topic.id))
            }
            Button("Reset to recommended topics") { prefs.followedTopics = Preferences.defaultTopics }
        } header: {
            Text("Topics I follow")
        } footer: {
            Text("\"For You\" boosts these topics and the topics of things you save. This happens on your iPhone; nothing about your interests is sent anywhere.")
        }
    }

    // MARK: Reading

    private var readingSection: some View {
        Section {
            Picker("Open items at", selection: $prefs.summaryLevel) {
                ForEach(SummaryLevel.allCases) { level in
                    Text(level.title).tag(level)
                }
            }
        } header: {
            Text("Summary detail level")
        } footer: {
            Text(prefs.summaryLevel.explanation + ". You can always switch between Quick, Technical and Explore on each item.")
        }
    }

    // MARK: Notifications

    private var notificationsSection: some View {
        Section {
            Toggle("Daily briefing reminder", isOn: Binding(get: { prefs.notifyBriefing }, set: { on in
                Task { await setBriefing(on) }
            }))
            if prefs.notifyBriefing {
                DatePicker("Time", selection: Binding(get: { prefs.briefingTime }, set: { newValue in
                    prefs.briefingTime = newValue
                    NotificationService.scheduleDailyBriefing(hour: prefs.briefingHour, minute: prefs.briefingMinute)
                }), displayedComponents: .hourAndMinute)
            }
            Toggle("Important news alerts", isOn: Binding(get: { prefs.notifyBreaking }, set: { on in
                Task { await setBreaking(on) }
            }))
            if notificationStatus == .denied {
                Button("Notifications are off. Open iPhone Settings") {
                    if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                }
            }
        } header: {
            Text("Notifications")
        } footer: {
            Text("Alerts cover items marked Important in your followed topics. iOS decides when apps refresh in the background (usually a few times a day), so alerts can be delayed. Push notifications from a server would need a paid Apple Developer account.")
        }
    }

    private func setBriefing(_ on: Bool) async {
        if on {
            let granted = await NotificationService.requestPermission()
            notificationStatus = await NotificationService.authorizationStatus()
            prefs.notifyBriefing = granted
            if granted { NotificationService.scheduleDailyBriefing(hour: prefs.briefingHour, minute: prefs.briefingMinute) }
        } else {
            prefs.notifyBriefing = false
            NotificationService.cancelDailyBriefing()
        }
    }

    private func setBreaking(_ on: Bool) async {
        if on {
            let granted = await NotificationService.requestPermission()
            notificationStatus = await NotificationService.authorizationStatus()
            prefs.notifyBreaking = granted
            if granted {
                prefs.backgroundRefresh = true
                NotificationService.scheduleBackgroundRefresh()
            }
        } else {
            prefs.notifyBreaking = false
        }
    }

    // MARK: Refresh

    private var refreshSection: some View {
        Section {
            Toggle("Background refresh", isOn: $prefs.backgroundRefresh)
            Button("Refresh everything now") {
                Task { await app.refresh() }
            }
            Button("Clear offline copy (\(cacheSize))") {
                APIClient.shared.cache.clear()
                cacheSize = APIClient.shared.cache.sizeDescription
                showCacheCleared = true
            }
            .alert("Offline copy cleared", isPresented: $showCacheCleared) {
                Button("OK", role: .cancel) {}
            } message: {
                Text("Your bookmarks and settings are untouched.")
            }
        } header: {
            Text("Refresh")
        } footer: {
            Text("The server collects new items every 15 minutes, official blogs every 30 minutes, GitHub discovery every 2 hours and repository metrics every 6 hours. Pull down on any screen to get the latest. Background refresh keeps an offline copy fresh.")
        }
    }

    // MARK: Appearance

    private var appearanceSection: some View {
        Section("Appearance") {
            Picker("Theme", selection: $prefs.appearance) {
                ForEach(Appearance.allCases) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
        }
    }

    // MARK: Status

    private var statusSection: some View {
        Section {
            if let meta = app.meta {
                LabeledContent("Server status") {
                    StatusPill(status: meta.status)
                }
                LabeledContent("Last update", value: Formatting.relative(iso: meta.generatedAt))
                if app.metaIsStale, let at = app.metaFetchedAt {
                    Text("Offline: status as of \(Formatting.relative(at))").font(.caption).foregroundStyle(.orange)
                }
                NavigationLink(value: Route.sources) {
                    LabeledContent("Data sources",
                                   value: "\(meta.sources.filter { $0.status == "ok" }.count) of \(meta.sources.filter { $0.status != "disabled" }.count) healthy")
                }
                if let llm = meta.llm {
                    LabeledContent("AI explanations", value: llm.configured ? "On" : "Not configured")
                    if llm.configured {
                        if let model = llm.model { LabeledContent("AI model", value: "\(llm.provider ?? "") · \(model)") }
                        LabeledContent("AI calls (24h)", value: "\(llm.successfulDay ?? 0) of \(llm.callsDay ?? 0) succeeded")
                        LabeledContent("Explanations cached", value: "\(llm.explanationsCached ?? 0)")
                        if let err = llm.lastError, let at = llm.lastErrorAt,
                           (DateParsing.parse(at) ?? .distantPast) > Date().addingTimeInterval(-6 * 3600) {
                            Text("Recent AI issue: \(err)").font(.caption).foregroundStyle(.orange)
                        }
                    }
                }
            } else if let error = app.metaError {
                Text(error).foregroundStyle(.secondary)
                Button("Retry") { Task { await app.loadMeta() } }
            } else {
                ProgressView()
            }
            LabeledContent("Backend", value: APIClient.shared.baseURL.host ?? "")
            Button("Change backend address (advanced)") {
                backendDraft = prefs.apiBaseOverride
                editingBackend = true
            }
            .font(.footnote)
            .alert("Backend address", isPresented: $editingBackend) {
                TextField(APIClient.defaultBaseURL.absoluteString, text: $backendDraft)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                Button("Save") { prefs.apiBaseOverride = backendDraft.trimmingCharacters(in: .whitespaces) }
                Button("Use default") { prefs.apiBaseOverride = "" }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Only change this if you moved the AI Radar backend. Must start with https://")
            }
        } header: {
            Text("Status")
        } footer: {
            Text("No passwords or API keys are stored in this app. The AI key lives only in GitHub's encrypted secrets.")
        }
    }

    private var aboutSection: some View {
        Section("About") {
            LabeledContent("Version", value: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")
            LabeledContent("Saved items", value: "\(bookmarks.entries.count)")
            if let notes = app.meta?.notes {
                ForEach(notes, id: \.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
            }
        }
    }
}

struct StatusPill: View {
    let status: String
    var body: some View {
        let color: Color = status == "ok" ? .green : (status == "degraded" ? .orange : (status == "disabled" ? .gray : (status == "pending" ? .blue : .red)))
        Text(status == "ok" ? "Healthy" : status.capitalized)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8).padding(.vertical, 3)
            .foregroundStyle(color)
            .background(Capsule().fill(color.opacity(0.15)))
    }
}

struct SourcesStatusView: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        List {
            if let meta = app.meta {
                let groups = Dictionary(grouping: meta.sources, by: { $0.group ?? "Other" })
                ForEach(groups.keys.sorted(), id: \.self) { group in
                    Section(group) {
                        ForEach(groups[group] ?? []) { source in
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Text(source.name).font(.subheadline.weight(.semibold))
                                    if source.official == true {
                                        Image(systemName: "checkmark.seal.fill").font(.caption).foregroundStyle(.green)
                                    }
                                    Spacer()
                                    StatusPill(status: source.status)
                                }
                                Text(detail(source)).font(.caption).foregroundStyle(.secondary)
                                if let err = source.lastError, source.status == "error" {
                                    Text(err).font(.caption2).foregroundStyle(.orange).lineLimit(3)
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }
                Section {
                    Text("Credibility is a fixed, published weight per source used in ranking. Sources that fail are retried automatically; the feed keeps working with the others.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                LoadingView(message: "Loading source status…")
            }
        }
        .navigationTitle("Data sources")
        .refreshable { await app.loadMeta() }
    }

    private func detail(_ s: SourceStatus) -> String {
        var parts: [String] = []
        if let last = s.lastSuccessAt { parts.append("updated \(Formatting.relative(iso: last))") }
        if let n = s.items, n > 0 { parts.append("\(n) items") }
        if let m = s.refreshMinutes { parts.append(m >= 60 ? "every \(m / 60)h" : "every \(m) min") }
        if let c = s.credibility { parts.append("credibility \(Int(c * 100))%") }
        return parts.joined(separator: " · ")
    }
}
