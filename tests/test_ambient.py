from moza.ambient import render_ambient
from moza.config import Profile, ProjectEnvScope


def test_render_matches_root_and_subdirs():
    profiles = {"ccp": Profile(name="ccp", project_env=[
        ProjectEnvScope(match="*/ccp/chemcopilot", env={"AWS_PROFILE": "ccp", "CCP": "$HOME/ccp/chemcopilot"}),
    ])}
    out = render_ambient(profiles)
    # matches on "$PWD/" so the directory root itself is covered, not just subdirs
    assert 'case "$PWD/" in */ccp/chemcopilot/*)' in out
    assert 'export AWS_PROFILE="ccp"' in out
    assert 'export CCP="$HOME/ccp/chemcopilot"' in out       # $HOME left for zsh


def test_render_trailing_glob_is_normalized():
    # a user who writes the old "/*"-style glob gets the same base
    profiles = {"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/ccp/chemcopilot/*", env={"K": "v"})])}
    assert 'case "$PWD/" in */ccp/chemcopilot/*)' in render_ambient(profiles)


def test_render_escapes_only_quote_and_backslash_keeps_dollar_and_backtick():
    profiles = {"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/x", env={"Q": 'a"b\\c', "V": "$HOME/y", "B": "x`y"})])}
    out = render_ambient(profiles)
    assert r'export Q="a\"b\\c"' in out       # " and \ escaped for string integrity
    assert 'export V="$HOME/y"' in out        # $ kept (feature)
    assert 'export B="x`y"' in out            # backtick NOT escaped — honestly eval'd


def test_render_empty_when_no_scopes():
    out = render_ambient({"p": Profile(name="p")})
    assert "# >>> moza ambient env" in out
    assert 'case "$PWD/"' not in out
