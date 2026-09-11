import pytest

from news_ingest.prominence import derive_prominence


@pytest.mark.parametrize(
    ("source", "surface", "position", "count", "publisher_order", "score", "tier"),
    [
        ("ft", "homepage_rss", 1, 11, None, 1.0, "high"),
        ("ft", "homepage_rss", 3, 11, None, 0.8182, "high"),
        ("nytimes", "homepage_rss", 19, 19, None, 0.0526, "low"),
        ("dr", "section_rss", 1, 20, None, 0.5, "medium"),
        ("dr", "latest_rss", 20, 20, None, 0.0325, "low"),
        ("politiken", "latest_rss", 9, 20, 2, 0.6175, "medium"),
    ],
)
def test_prominence_scores(source, surface, position, count, publisher_order, score, tier):
    result = derive_prominence(
        source=source,
        surface=surface,
        position=position,
        snapshot_item_count=count,
        publisher_order=publisher_order,
    )
    assert result.score == score
    assert result.tier == tier


def test_invalid_positions_are_rejected():
    with pytest.raises(ValueError):
        derive_prominence(source="ft", surface="homepage_rss", position=0, snapshot_item_count=10)
