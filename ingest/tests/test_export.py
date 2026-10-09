"""The export's appearances are the exported articles' own, selected in SQL rather than by reading
the whole table."""

import json

from test_replay import history  # noqa: F401 -- the populated database fixture

from news_ingest.cli import main


def test_export_carries_only_the_windowed_articles_appearances(history, tmp_path, capsys):  # noqa: F811
    db, config_file, _config = history
    con = db.con
    # An article outside the window, with a sighting that reuses an existing poll.
    poll_id = con.execute("SELECT poll_id FROM appearances LIMIT 1").fetchone()[0]
    con.execute(
        "INSERT INTO articles(source,source_id,snapshot_json,published_at,last_changed_at,canonical_url,content_hash) VALUES(?,?,?,?,?,?,?)",
        (
            "bbc",
            "elsewhere",
            json.dumps({"source": "bbc", "source_id": "elsewhere"}),
            "2026-09-20T00:00:00.000000Z",
            "2026-09-20T00:00:00.000000Z",
            "https://example.com/x",
            "sha256:x",
        ),
    )
    con.execute(
        "INSERT INTO appearances(poll_id,source,source_id,surface_id,surface,surface_section,position,publisher_order,is_super_article,observed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            poll_id,
            "bbc",
            "elsewhere",
            "bbc.old",
            "section_rss",
            None,
            99,
            1,
            None,
            "2026-09-20T00:01:00.000000Z",
        ),
    )
    con.commit()
    expected = con.execute(
        "SELECT p.poll_id,p.source,p.source_id,p.surface_id,p.position FROM appearances p JOIN articles a ON a.source=p.source AND a.source_id=p.source_id "
        "WHERE a.published_at>=? AND a.published_at<? ORDER BY p.observed_at,p.source,p.source_id,p.surface_id,p.position",
        ("2026-09-29T00:00:00.000000Z", "2026-09-30T00:00:00.000000Z"),
    ).fetchall()
    assert expected and all(r[2] != "elsewhere" for r in expected)
    output = tmp_path / "bundle"
    assert (
        main(
            [
                "export",
                "--config",
                str(config_file),
                "--since",
                "2026-09-29T00:00:00Z",
                "--until",
                "2026-09-30T00:00:00Z",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    capsys.readouterr()
    exported = [
        json.loads(line) for line in (output / "appearances.jsonl").read_text().splitlines()
    ]
    assert [
        (e["poll_id"], e["source"], e["source_id"], e["surface_id"], e["position"])
        for e in exported
    ] == [tuple(r) for r in expected]
    assert all(e["source_id"] != "elsewhere" for e in exported)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["appearance_count"] == len(expected)
