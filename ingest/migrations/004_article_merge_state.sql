CREATE TABLE IF NOT EXISTS article_feed_merge_state (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    feed_id TEXT NOT NULL,
    state_json TEXT NOT NULL CHECK(json_valid(state_json)),
    PRIMARY KEY(source, source_id, feed_id)
);
CREATE TABLE IF NOT EXISTS article_merge_heads (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    last_sighting_id INTEGER NOT NULL,
    state_count INTEGER NOT NULL CHECK(state_count > 0),
    PRIMARY KEY(source, source_id)
);
