"""Generate git `includeIf` config so a commit is authored as the right identity
natively — the prevention counterpart to the `guard` refusal.

`mien git sync` renders one gitconfig per profile (its `[user] email`/`name`) and
a top-level file of `includeIf` conditions pointing at them: by repository owner
(`hasconfig:remote.*.url`, from `owns_remotes`) and by workspace directory
(`gitdir`, from approved `.mien` declarations). Wiring `~/.gitconfig` to include
that file lets git itself stamp the correct author in every repo an identity
owns, so the wrong-author commit never happens rather than being blocked after
the fact. Analogous to `env sync` writing `ambient.zsh` and sourcing it from
`~/.zshenv`.
"""

from __future__ import annotations

from pathlib import Path

from mien.config import Profile, config_path

_MANAGED_HEADER = (
    "# Managed by mien — do not edit; regenerate with `mien git sync`.\n"
)


def default_git_email(profile: Profile) -> str | None:
    """The email to offer when a profile has no explicit `git_email` yet."""
    if profile.google and profile.google.email:
        return profile.google.email
    if profile.atlassian and profile.atlassian.email:
        return profile.atlassian.email
    return None


def default_git_name(profile: Profile) -> str | None:
    if profile.github and profile.github.username:
        return profile.github.username
    return None


def git_identity(profile: Profile) -> tuple[str, str] | None:
    """(email, name) for a profile's git author, or None if no email is known.

    Prefers the explicit `git_email`/`git_name`; falls back to the account email
    and GitHub username, and to the email's local part for a missing name.
    """
    email = profile.git_email or default_git_email(profile)
    if not email:
        return None
    name = profile.git_name or default_git_name(profile) or email.split("@", 1)[0]
    return email, name


def hasconfig_patterns(owns_remote: str) -> list[str]:
    """git `hasconfig:remote.*.url` globs for an `owns_remotes` entry.

    An `owns_remotes` value is a canonical `host/owner[/...]` glob. A repository's
    `origin` reaches git as either `https://host/owner/repo` (a `/` before the
    host) or the scp form `git@host:owner/repo` (a `:`), which git's glob matches
    differently — `**/` crosses the `//` of a URL scheme, but a leading `**` does
    not — so two conditions are emitted, one per shape. Both were verified
    against real `git config` resolution.
    """
    base = owns_remote.strip().rstrip("/")
    if base.endswith("/*"):
        base = base[:-2]
    host, sep, path = base.partition("/")
    if not sep or not path:
        return []
    return [
        f"hasconfig:remote.*.url:**/*{host}/{path}/**",  # https:// ssh:// git:// (opt. user@)
        f"hasconfig:remote.*.url:**{host}:{path}/**",    # scp: git@host:owner/…
    ]


def gitdir_pattern(directory: str) -> str:
    """git `gitdir` glob matching every repository at or under ``directory``."""
    return f"gitdir:{str(Path(directory))}/**"


def _config_dir() -> Path:
    return config_path().parent


def profile_gitconfig_path(profile_name: str) -> Path:
    return _config_dir() / "git" / f"{profile_name}.gitconfig"


def main_gitconfig_path() -> Path:
    return _config_dir() / "gitconfig"


def render_profile_gitconfig(email: str, name: str) -> str:
    return f"{_MANAGED_HEADER}[user]\n\temail = {email}\n\tname = {name}\n"


def render_main_gitconfig(blocks: list[tuple[str, str]]) -> str:
    """``blocks`` is a list of (includeIf-condition, profile-gitconfig-path)."""
    out = [_MANAGED_HEADER]
    for condition, path in blocks:
        out.append(f'[includeIf "{condition}"]\n\tpath = {path}\n')
    return "".join(out)
