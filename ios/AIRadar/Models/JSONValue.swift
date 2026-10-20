import Foundation

/// A tolerant JSON value. AI-generated explanation fields can come back as a string, a list or an
/// object depending on the model, so we decode them loosely and render whatever is there.
enum JSONValue: Decodable, Hashable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case array([JSONValue])
    case object([String: JSONValue])
    case null

    init(from decoder: Decoder) throws {
        if let keyed = try? decoder.container(keyedBy: AnyKey.self) {
            var dict: [String: JSONValue] = [:]
            for key in keyed.allKeys {
                dict[key.stringValue] = (try? keyed.decode(JSONValue.self, forKey: key)) ?? .null
            }
            self = .object(dict)
            return
        }
        if var unkeyed = try? decoder.unkeyedContainer() {
            var items: [JSONValue] = []
            while !unkeyed.isAtEnd {
                items.append((try? unkeyed.decode(JSONValue.self)) ?? .null)
            }
            self = .array(items)
            return
        }
        let single = try decoder.singleValueContainer()
        if single.decodeNil() {
            self = .null
        } else if let b = try? single.decode(Bool.self) {
            self = .bool(b)
        } else if let n = try? single.decode(Double.self) {
            self = .number(n)
        } else if let s = try? single.decode(String.self) {
            self = .string(s)
        } else {
            self = .null
        }
    }

    /// Key lookup that ignores underscores and case, so "why_it_matters" and "whyItMatters" both work.
    subscript(_ key: String) -> JSONValue? {
        guard case .object(let dict) = self else { return nil }
        if let exact = dict[key] { return exact }
        let wanted = JSONValue.normalize(key)
        return dict.first { JSONValue.normalize($0.key) == wanted }?.value
    }

    static func normalize(_ key: String) -> String {
        key.replacingOccurrences(of: "_", with: "").lowercased()
    }

    /// Readable text for any value.
    var text: String? {
        switch self {
        case .string(let s):
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : t
        case .number(let n):
            return n.rounded() == n ? String(Int(n)) : String(n)
        case .bool(let b):
            return b ? "Yes" : "No"
        case .array(let items):
            let parts = items.compactMap { $0.text }
            return parts.isEmpty ? nil : parts.joined(separator: "\n")
        case .object(let dict):
            let parts = dict.keys.sorted().compactMap { key -> String? in
                guard let value = dict[key]?.text else { return nil }
                return "\(key): \(value)"
            }
            return parts.isEmpty ? nil : parts.joined(separator: "; ")
        case .null:
            return nil
        }
    }

    /// A list of strings: arrays become their elements, a single string becomes a one-item list.
    var list: [String] {
        switch self {
        case .array(let items):
            return items.compactMap { item -> String? in
                if case .object = item {
                    if let term = item["term"]?.text, let meaning = item["meaning"]?.text { return "\(term): \(meaning)" }
                }
                return item.text
            }
        case .null:
            return []
        default:
            return text.map { [$0] } ?? []
        }
    }

    /// Glossary-style pairs.
    var terms: [(term: String, meaning: String)] {
        guard case .array(let items) = self else { return [] }
        return items.compactMap { item in
            if let term = item["term"]?.text {
                return (term, item["meaning"]?.text ?? "")
            }
            if let s = item.text { return (s, "") }
            return nil
        }
    }
}

struct AnyKey: CodingKey {
    var stringValue: String
    var intValue: Int?
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { self.stringValue = String(intValue); self.intValue = intValue }
}
