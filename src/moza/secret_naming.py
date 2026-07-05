from __future__ import annotations


def render_name(template: str, **tokens: str) -> str:
    return template.format_map(_StrictDict(tokens))


class _StrictDict(dict):
    def __missing__(self, key: str) -> str:
        raise KeyError(f"missing token {{{key}}} in template")
