"""Render the mien identity segment for a Claude Code status line.

The segment answers one question, always in view: *who am I acting as here* —
and turns red the moment the answer is wrong. An agent session that inherited
one identity from the shell it was launched in, sitting in a directory that
belongs to a different identity, is exactly how a personal commit lands in a
work repository. The status line makes that visible before it happens.

The rendering is pure and secret-free by construction: it takes only two profile
*names* (never a token) and formats them, so it is safe to call at status-line
frequency.
"""

from __future__ import annotations

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"


def render_segment(
    env_profile: str | None,
    claimed_profile: str | None,
    *,
    source: str = "dir",
    ambiguous: bool = False,
    env_unknown: bool = False,
) -> str:
    """Format the mien identity segment.

    Arguments are mien's two independent signals for "who am I here":
    - ``env_profile``: the ``MIEN_PROFILE`` active in this session (inherited
      from the launching shell), or ``None``.
    - ``claimed_profile``: the profile this location claims — by the repository's
      remote owner or by a directory ``default_for`` scope — or ``None``.
    - ``source``: ``"repo"`` if the claim came from the git remote owner,
      ``"dir"`` if from a directory scope; only affects the mismatch wording.
    - ``ambiguous``: the location is claimed by two profiles with equal
      specificity (resolution would refuse to guess).
    - ``env_unknown``: ``MIEN_PROFILE`` names a profile that is not in the
      config (renamed or deleted, leaving a stale export in an open shell).

    The alarm cases come first: a wrong or unknown active identity is the failure
    this segment exists to surface, so it must win over the calm cases.
    """
    # An active profile that no longer exists — a stale export in this shell.
    if env_profile and env_unknown:
        return f"{_RED}🔴 mien:{env_profile} ✗ unknown profile{_RESET}"
    # Active identity disagrees with what this location claims: you are set up to
    # act as the wrong person here. The core catch.
    if env_profile and claimed_profile and env_profile != claimed_profile:
        why = (f"repo is {claimed_profile}'s" if source == "repo"
               else f"dir wants {claimed_profile}")
        return f"{_RED}🔴 mien:{env_profile} ✗ {why}{_RESET}"
    # The location is claimed ambiguously and nothing is set to break the tie —
    # mien would refuse to route; surface it rather than pick silently.
    if ambiguous and not env_profile:
        return f"{_RED}🔴 mien:? ✗ ambiguous{_RESET}"
    # A single definite identity: an explicit MIEN_PROFILE wins, else the claim.
    active = env_profile or claimed_profile
    if active:
        return f"{_GREEN}🟢 mien:{active}{_RESET}"
    # Nothing set, and nothing claims this location.
    return f"{_YELLOW}🟡 mien:— no profile here{_RESET}"
