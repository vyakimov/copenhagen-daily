-- compact-history keeps the first and last row of an unbroken run of identical observations in
-- consecutive successful polls of one feed. run_polls on the first row counts the polls the run
-- covers; the rows between were removed and are the feed's successful polls in between.
ALTER TABLE sightings ADD COLUMN run_polls INTEGER CHECK(run_polls IS NULL OR run_polls>2);
ALTER TABLE appearances ADD COLUMN run_polls INTEGER CHECK(run_polls IS NULL OR run_polls>2);

-- Older raw payloads move into one xz archive per feed and UTC day; each body keeps an index row.
CREATE TABLE raw_payload_archives (
    archive_id INTEGER PRIMARY KEY,
    feed_id TEXT NOT NULL,
    day TEXT NOT NULL,
    compression TEXT NOT NULL CHECK(compression='xz'),
    payload BLOB NOT NULL,
    member_count INTEGER NOT NULL CHECK(member_count>0),
    uncompressed_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE raw_payload_members (
    content_hash TEXT PRIMARY KEY,
    archive_id INTEGER NOT NULL REFERENCES raw_payload_archives(archive_id),
    archive_offset INTEGER NOT NULL CHECK(archive_offset>=0),
    uncompressed_bytes INTEGER NOT NULL,
    first_poll_id INTEGER NOT NULL REFERENCES feed_polls(poll_id),
    first_observed_at TEXT NOT NULL
);
CREATE INDEX raw_payload_members_archive_idx ON raw_payload_members(archive_id);
CREATE INDEX raw_payloads_observed_idx ON raw_payloads(first_observed_at);
