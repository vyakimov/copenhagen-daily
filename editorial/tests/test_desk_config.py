from news_editorial.run import load_desk_config


def test_the_local_overlay_fills_in_deployment_names_one_level_deep(tmp_path):
    base = tmp_path / "desk.yaml"
    base.write_text("publish_root: x\ndelivery:\n  bucket: null\n  aws_command: aws\n")
    local = tmp_path / "desk.local.yaml"
    local.write_text("delivery:\n  bucket: live-bucket\n")
    config = load_desk_config(base, local)
    assert config["delivery"] == {"bucket": "live-bucket", "aws_command": "aws"}
    assert config["publish_root"] == "x"
    assert load_desk_config(base, tmp_path / "missing.yaml")["delivery"]["bucket"] is None
