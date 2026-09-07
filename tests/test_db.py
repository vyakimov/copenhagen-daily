from news_ingest.db import Database


def test_migrations_are_idempotent(tmp_path):
    one = Database(tmp_path / "news.sqlite")
    assert one.con.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 2
    one.close()
    two = Database(tmp_path / "news.sqlite")
    assert two.con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    two.close()
