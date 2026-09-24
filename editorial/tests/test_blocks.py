import stat

import pytest

from news_editorial.blocks import BlockError, call_wrapper


def _fake(tmp_path, body: str):
    script = tmp_path / "fake.sh"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_ok_envelope_returns_result(tmp_path):
    script = _fake(tmp_path, 'printf \'%s\\n\' \'{"ok":true,"action":"x","result":{"n":1}}\'\n')
    assert call_wrapper(script, "x") == {"n": 1}


def test_failed_envelope_raises_block_error(tmp_path):
    script = _fake(tmp_path, 'printf \'%s\\n\' \'{"ok":false,"action":"x","error":{"type":"lock_busy","message":"m"}}\'; exit 1\n')
    with pytest.raises(BlockError) as info:
        call_wrapper(script, "x")
    assert info.value.error_type == "lock_busy"


def test_garbage_stdout_raises_block_error(tmp_path):
    script = _fake(tmp_path, "echo not json\n")
    with pytest.raises(BlockError) as info:
        call_wrapper(script, "x")
    assert info.value.error_type == "block_protocol"
