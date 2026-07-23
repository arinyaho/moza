import pytest

from mien.secret_naming import render_name


def test_renders_default_template():
    assert render_name(
        "mien-{profile}-{service}-{kind}",
        profile="personal", service="google", kind="refresh",
    ) == "mien-personal-google-refresh"


def test_renders_slack_template_with_workspace():
    assert render_name(
        "mien-{profile}-slack-{workspace}-token",
        profile="work", workspace="team-a",
    ) == "mien-work-slack-team-a-token"


def test_missing_token_raises():
    with pytest.raises(KeyError):
        render_name("mien-{profile}-{kind}", profile="x")
