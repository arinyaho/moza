"""Live identity verification for `moza whoami --live`.

The offline `whoami` prints what the config claims a profile is. That cannot
catch this tool's real failure mode — acting as the wrong identity because the
environment was never activated, was activated for a different profile, or holds
a revoked token. These probes ask each provider who it actually authenticates as
and compare that to the configured value.

Each probe returns a ProbeResult rather than raising, so one dead service does
not hide the others, and a mismatch is reported distinctly from a dead token
(they need different remedies) and from a probe that could not run at all.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum

import httpx

from moza.oauth import exchange_refresh_token

_PROBE_TIMEOUT = 15


class Status(Enum):
    MATCH = "match"                # live subject equals the configured one
    MISMATCH = "mismatch"          # live subject differs — wrong identity
    UNCOMPARABLE = "uncomparable"  # live subject obtained, but nothing to compare it to
    UNAUTHORIZED = "unauthorized"  # the credential was rejected — revoked or expired
    UNREACHABLE = "unreachable"    # the provider could not be reached
    UNAVAILABLE = "unavailable"    # the tool needed to ask is not installed


@dataclass
class ProbeResult:
    service: str
    configured: str | None
    live: str | None
    status: Status
    detail: str = ""


def _compare(service: str, configured: str | None, live: str) -> ProbeResult:
    if configured is None:
        return ProbeResult(service, configured, live, Status.UNCOMPARABLE)
    if live == configured:
        return ProbeResult(service, configured, live, Status.MATCH)
    return ProbeResult(service, configured, live, Status.MISMATCH)


# A CLI's stderr is the only thing that distinguishes a rejected credential from
# an unreachable network — both exit non-zero. These substrings mark the network
# case for `gh` and `aws`; anything else non-zero is treated as an auth failure.
# Getting this wrong in the network direction is the costly one: it would fail the
# gate offline and name the wrong remedy, so the default leans to UNAUTHORIZED
# (a real problem to surface) only when the text does not look like a network error.
_NETWORK_ERROR_MARKERS = (
    "could not connect",
    "error connecting",
    "connection refused",
    "no such host",
    "temporary failure in name resolution",
    "network is unreachable",
    "timed out",
    "timeout",
    "dial tcp",
    "no route to host",
)


def _classify_cli_failure(service: str, stderr: str) -> ProbeResult:
    lowered = stderr.lower()
    if any(m in lowered for m in _NETWORK_ERROR_MARKERS):
        return ProbeResult(service, None, None, Status.UNREACHABLE, stderr)
    return ProbeResult(service, None, None, Status.UNAUTHORIZED, stderr)


def _run_probe(service: str, cmd: list[str], env: dict[str, str]) -> tuple[str | None, ProbeResult | None]:
    """Run a CLI probe under `env`. Returns (stdout_stripped, None) on success,
    or (None, ProbeResult) when the failure is itself the answer."""
    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, timeout=_PROBE_TIMEOUT
        )
    except FileNotFoundError:
        return None, ProbeResult(service, None, None, Status.UNAVAILABLE,
                                 f"{cmd[0]} is not installed")
    except subprocess.TimeoutExpired:
        return None, ProbeResult(service, None, None, Status.UNREACHABLE,
                                 f"{cmd[0]} timed out")
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        return None, _classify_cli_failure(service, stderr)
    return proc.stdout.decode("utf-8", "replace").strip(), None


def probe_github(configured_username: str | None, env: dict[str, str]) -> ProbeResult:
    live, failed = _run_probe("github", ["gh", "api", "user", "-q", ".login"], env)
    if failed is not None:
        return failed
    return _compare("github", configured_username, live)


def probe_aws(configured_profile: str | None, env: dict[str, str]) -> ProbeResult:
    live, failed = _run_probe(
        "aws",
        ["aws", "sts", "get-caller-identity", "--query", "Arn", "--output", "text"],
        env,
    )
    if failed is not None:
        return failed
    # A profile name is not an ARN, so there is nothing to match against — report
    # the live caller and leave the judgement to the reader.
    return ProbeResult("aws", configured_profile, live, Status.UNCOMPARABLE)


class _NoEmail(Exception):
    """userinfo returned 200 but no email — e.g. a token minted without the
    email scope. Raised so probe_google can report it rather than crash."""


def _userinfo_email(access_token: str) -> str:
    resp = httpx.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_PROBE_TIMEOUT,
    )
    resp.raise_for_status()
    email = resp.json().get("email")
    if not email:
        raise _NoEmail("userinfo response has no email field")
    return email


def probe_google(
    configured_email: str | None,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> ProbeResult:
    # exchange_refresh_token and _userinfo_email both use httpx: a 4xx (a revoked
    # or expired refresh token yields 400 invalid_grant) is a dead credential;
    # any other transport error is the provider being unreachable.
    try:
        access = exchange_refresh_token(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
        live = _userinfo_email(access)
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        # 429 is a valid credential being rate-limited, not a dead one, so it is
        # unreachable-for-now rather than unauthorized — only 4xx that is not 429
        # means the credential itself was rejected.
        dead = 400 <= code < 500 and code != 429
        status = Status.UNAUTHORIZED if dead else Status.UNREACHABLE
        return ProbeResult("google", configured_email, None, status, f"HTTP {code}")
    except httpx.RequestError as e:
        return ProbeResult("google", configured_email, None, Status.UNREACHABLE, str(e))
    except _NoEmail as e:
        return ProbeResult("google", configured_email, None, Status.UNREACHABLE, str(e))
    return _compare("google", configured_email, live)
