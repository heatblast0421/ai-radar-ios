import Foundation

enum APIError: LocalizedError {
    case badStatus(Int)
    case notFound
    case offline
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .badStatus(let code):
            return "The AI Radar server answered with an error (\(code)). Please try again in a minute."
        case .notFound:
            return "This item is no longer available. It may have expired from the feed."
        case .offline:
            return "Can't reach the AI Radar server. Check your internet connection and try again."
        case .decoding:
            return "The data from the server couldn't be read. An app update may be needed."
        }
    }
}

struct Loaded<T> {
    let value: T
    /// True when the network failed and this came from the on-device copy.
    let isStale: Bool
    let fetchedAt: Date
}

/// Reads the static JSON API. Every successful response is also saved on the device, so the app keeps
/// working offline with the last copy (clearly marked as such).
final class APIClient {
    static let shared = APIClient()
    static let defaultBaseURL = URL(string: "https://heatblast0421.github.io/ai-radar-ios/api/v1/")!

    let cache = DiskCache()
    private let session: URLSession
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    init(session: URLSession? = nil) {
        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.default
            config.timeoutIntervalForRequest = 20
            config.timeoutIntervalForResource = 60
            config.requestCachePolicy = .reloadRevalidatingCacheData
            self.session = URLSession(configuration: config)
        }
    }

    var baseURL: URL {
        let override = UserDefaults.standard.string(forKey: Preferences.Keys.apiBaseOverride) ?? ""
        let trimmed = override.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty, let url = URL(string: trimmed.hasSuffix("/") ? trimmed : trimmed + "/"), url.scheme == "https" {
            return url
        }
        return Self.defaultBaseURL
    }

    func url(for path: String) -> URL {
        URL(string: path, relativeTo: baseURL)?.absoluteURL ?? baseURL.appendingPathComponent(path)
    }

    func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        try decoder.decode(T.self, from: data)
    }

    func get<T: Decodable>(_ path: String, as type: T.Type, allowStale: Bool = true) async throws -> Loaded<T> {
        var request = URLRequest(url: url(for: path))
        request.cachePolicy = .reloadRevalidatingCacheData
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw APIError.badStatus(0) }
            if http.statusCode == 404 { throw APIError.notFound }
            guard (200..<300).contains(http.statusCode) else { throw APIError.badStatus(http.statusCode) }
            do {
                let value = try decoder.decode(T.self, from: data)
                cache.store(data, for: path)
                return Loaded(value: value, isStale: false, fetchedAt: Date())
            } catch {
                throw APIError.decoding(String(describing: error))
            }
        } catch {
            // A cancelled request (e.g. iOS ending a pull-to-refresh early) is not "offline".
            if APIClient.isCancellation(error) { throw CancellationError() }
            if case APIError.notFound = error { throw error }
            if allowStale, let cached = cache.load(for: path), let value = try? decoder.decode(T.self, from: cached.data) {
                return Loaded(value: value, isStale: true, fetchedAt: cached.date)
            }
            if let apiError = error as? APIError { throw apiError }
            throw APIError.offline
        }
    }

    static func isCancellation(_ error: Error) -> Bool {
        error is CancellationError || (error as? URLError)?.code == .cancelled
    }

    /// Cached copy only (used for instant display before the network answers).
    func cached<T: Decodable>(_ path: String, as type: T.Type) -> Loaded<T>? {
        guard let cached = cache.load(for: path), let value = try? decoder.decode(T.self, from: cached.data) else { return nil }
        return Loaded(value: value, isStale: true, fetchedAt: cached.date)
    }
}

/// Simple file cache in the app's Caches folder.
final class DiskCache {
    private let folder: URL

    init(folderName: String = "api-cache") {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
        folder = base.appendingPathComponent(folderName, isDirectory: true)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    private func file(for path: String) -> URL {
        let safe = path.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: ":", with: "_")
        return folder.appendingPathComponent(safe)
    }

    func store(_ data: Data, for path: String) {
        try? data.write(to: file(for: path), options: .atomic)
    }

    func load(for path: String) -> (data: Data, date: Date)? {
        let url = file(for: path)
        guard let data = try? Data(contentsOf: url) else { return nil }
        let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
        let date = (attrs?[.modificationDate] as? Date) ?? Date.distantPast
        return (data, date)
    }

    func clear() {
        try? FileManager.default.removeItem(at: folder)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    var sizeDescription: String {
        let files = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.fileSizeKey])) ?? []
        let bytes = files.reduce(0) { total, url in
            total + ((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
        }
        return ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }
}
