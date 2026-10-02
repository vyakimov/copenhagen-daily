from news_editorial.wire import wire_agency

SIGNOFFS = {"ritzau": "RITZAU"}


def _article(description, authors=()):
    return {"source": "kristeligt_dagblad", "description": description, "authors": list(authors)}


def test_an_unsigned_article_ending_in_the_sign_off_is_wire_copy():
    assert wire_agency(_article("<p>Den 43-årige kan anke til landsretten.</p><p>RITZAU</p>"), SIGNOFFS) == "ritzau"
    assert wire_agency(_article("Den 43-årige kan anke til landsretten.  RITZAU"), SIGNOFFS) == "ritzau"


def test_a_sign_off_shared_with_a_foreign_agency_is_still_wire_copy():
    assert wire_agency(_article("Det oplyser OpenAI.</p><p>RITZAU/Reuters</p>"), SIGNOFFS) == "ritzau"


def test_a_bylined_article_is_the_outlets_own():
    assert wire_agency(_article("Partiet er langt fra magten.</p><p>RITZAU</p>", ["Jens From Lyng"]), SIGNOFFS) is None


def test_a_mention_or_a_photo_credit_is_not_a_sign_off():
    assert wire_agency(_article("Putin udvider hæren, skriver flere internationale medier og Ritzau."), SIGNOFFS) is None
    assert wire_agency(_article("Paven talte fredag. Foto: Remo Casilli/Reuters/Ritzau Scanpix"), SIGNOFFS) is None
    assert wire_agency(_article("RITZAU forsøger at få oplyst, hvordan det skete."), SIGNOFFS) is None


def test_an_article_without_text_is_not_wire_copy():
    assert wire_agency(_article(None), SIGNOFFS) is None
    assert wire_agency(_article(""), SIGNOFFS) is None
