-- Discovery hints (e.g. "spotted on Trendshift") and AI relevance for repositories.
ALTER TABLE repos ADD COLUMN spotted_on TEXT NOT NULL DEFAULT '[]';
ALTER TABLE repos ADD COLUMN ai_relevance REAL NOT NULL DEFAULT 0;
