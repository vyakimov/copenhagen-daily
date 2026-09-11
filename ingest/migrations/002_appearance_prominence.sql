ALTER TABLE appearances ADD COLUMN snapshot_item_count INTEGER;
ALTER TABLE appearances ADD COLUMN prominence_score REAL;
ALTER TABLE appearances ADD COLUMN prominence_tier TEXT;
ALTER TABLE appearances ADD COLUMN prominence_evidence TEXT;

UPDATE appearances
SET snapshot_item_count = COALESCE(
        (SELECT parsed_item_count FROM feed_polls WHERE feed_polls.poll_id = appearances.poll_id),
        position
    );

UPDATE appearances
SET prominence_score = ROUND(
        CASE surface
            WHEN 'homepage' THEN 1.0
            WHEN 'homepage_rss' THEN 1.0
            WHEN 'latest_rss' THEN 0.65
            ELSE 0.50
        END
        * (snapshot_item_count - MIN(
            CASE
                WHEN source = 'politiken' AND publisher_order IS NOT NULL THEN publisher_order
                ELSE position
            END,
            snapshot_item_count
        ) + 1.0) / snapshot_item_count,
        4
    );

UPDATE appearances
SET prominence_tier = CASE
        WHEN prominence_score >= 0.75 THEN 'high'
        WHEN prominence_score >= 0.40 THEN 'medium'
        ELSE 'low'
    END,
    prominence_evidence = surface || ':' || CASE
        WHEN source = 'politiken' AND publisher_order IS NOT NULL THEN 'publisher_order'
        ELSE 'feed_position'
    END;
