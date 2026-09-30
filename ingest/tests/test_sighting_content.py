import json

import pytest

from news_ingest.sighting_content import restore_observation, split_observation, storage_digest


@pytest.mark.parametrize(
    "original",
    [
        "{}",
        json.dumps({"title": 'Æble "quoted"', "first_seen_at": "a"}, ensure_ascii=False, indent=2),
        '{"first_seen_at":"a","nested":{"first_seen_at":"keep"},"last_seen_at":"b"}',
        '{"first_seen_at":"first","first_seen_at":"second","last_checked_at":null}',
        '{"first_seen_at":"a","description":"first_seen_at: null", "number":1.2300e+3}',
        '{"first_seen_at":"a", "last_seen_at" : "b", "last_checked_at":"c"}',
    ],
)
def test_observation_codec_preserves_every_original_byte(original):
    template, timestamps = split_observation(original)
    assert restore_observation(template, timestamps) == original
    json.loads(template)


def test_only_top_level_observation_values_are_factored_out():
    original = '{"first_seen_at":"old","last_seen_at":"old","raw_metadata":{"time":"old"}}'
    later = original.replace('"first_seen_at":"old"', '"first_seen_at":"new"')
    assert split_observation(original)[0] == split_observation(later)[0]
    changed_raw = original.replace('"time":"old"', '"time":"new"')
    assert split_observation(original)[0] != split_observation(changed_raw)[0]


def test_storage_digest_includes_raw_evidence_and_identity():
    base = ["bbc", "one", '{"raw_url":"https://example.com/?tracking=1"}', "{}", "{}"]
    digest = storage_digest(*base)
    for index in range(len(base)):
        changed = list(base)
        changed[index] += "different"
        assert storage_digest(*changed) != digest


@pytest.mark.parametrize("text", ["[]", '{"a":1,}', '{"a":1} trailing', '{"a" 1}'])
def test_invalid_object_is_rejected(text):
    with pytest.raises(ValueError):
        split_observation(text)
