import Foundation

/// "For You" ranking, computed on the phone so your interests never leave the device.
/// personal score = server score (transparent, rule-based)
///                + up to 15 for topics you follow
///                + up to 8 for topics you tend to save
///                - 12 if the item matches none of your followed topics (when you follow any)
enum PersonalRanker {
    struct Result {
        let card: FeedCard
        let score: Double
        let matchedTopics: [String]
    }

    static func rank(_ cards: [FeedCard], followed: Set<String>, affinity: [String: Int]) -> [Result] {
        let maxAffinity = max(1, affinity.values.max() ?? 1)
        return cards.map { card in
            let matched = card.topics.filter { followed.contains($0) }
            var score = card.score
            if !matched.isEmpty {
                score += min(15, 9 + 3 * Double(matched.count - 1))
            } else if !followed.isEmpty {
                score -= 12
            }
            let aff = card.topics.map { Double(affinity[$0] ?? 0) / Double(maxAffinity) }.max() ?? 0
            score += 8 * aff
            if card.importance == "high" { score += 3 }
            return Result(card: card, score: score, matchedTopics: matched)
        }
        .sorted { lhs, rhs in
            lhs.score == rhs.score ? lhs.card.id < rhs.card.id : lhs.score > rhs.score
        }
    }
}
