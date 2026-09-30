from news_editorial.deliver import push_device


def test_push_device_copies_the_current_page_with_legacy_scp(tmp_path):
    live = tmp_path / "live" / "device"
    live.mkdir(parents=True)
    (live / "current.png").write_bytes(b"png")
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    result = push_device(tmp_path, {"host": "nas", "path": "/volume1/web/todays_news.png"}, run=run)
    assert calls == [["scp", "-O", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", str(live / "current.png"), "nas:/volume1/web/todays_news.png"]]
    assert result == {"pushed": True, "to": "nas:/volume1/web/todays_news.png", "bytes": 3}


def test_push_device_is_skipped_without_a_host_and_fails_without_a_page(tmp_path):
    assert push_device(tmp_path, {})["skipped"] is True
    try:
        push_device(tmp_path, {"host": "h", "path": "/p.png"}, run=lambda *a, **k: None)
    except RuntimeError as exc:
        assert "current.png" in str(exc)
    else:
        raise AssertionError("expected a failure without a device page")
