import pytest

from moza.secret_naming import render_name


def test_renders_default_template():
    assert render_name(
        "hat-{profile}-{service}-{kind}",
        profile="personal", service="google", kind="refresh",
    ) == "hat-personal-google-refresh"


def test_renders_slack_template_with_workspace():
    assert render_name(
        "hat-{profile}-slack-{workspace}-token",
        profile="work", workspace="team-a",
    ) == "hat-work-slack-team-a-token"


def test_missing_token_raises():
    with pytest.raises(KeyError):
        render_name("hat-{profile}-{kind}", profile="x")
