-- Populated legacy databases require the explicit, backed-up deduplicate-sightings command.
-- db.py performs and verifies the lossless transfer in this migration's transaction.
CREATE TABLE sighting_contents (
    content_id INTEGER PRIMARY KEY,
    storage_hash TEXT NOT NULL UNIQUE,
    normalized_template TEXT NOT NULL CHECK(json_valid(normalized_template)),
    raw_metadata_json TEXT NOT NULL CHECK(json_valid(raw_metadata_json)),
    raw_item_json TEXT NOT NULL CHECK(json_valid(raw_item_json))
);
CREATE TABLE sightings_v5 (
    sighting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id INTEGER NOT NULL REFERENCES feed_polls(poll_id),
    feed_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    item_position INTEGER NOT NULL CHECK(item_position>0),
    publisher_order INTEGER,
    observed_at TEXT NOT NULL,
    content_id INTEGER NOT NULL REFERENCES sighting_contents(content_id),
    observation_json TEXT NOT NULL CHECK(json_valid(observation_json)),
    UNIQUE(feed_id,source_id,poll_id)
);
