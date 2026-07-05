#!/usr/bin/env python3
"""One-time hat -> moza migration. Run once per machine, then delete.

Essential (always): copy ~/.config/hat/config.json -> ~/.config/moza/config.json,
rewrite secret_naming templates to moza-*, re-push the config manifest under
moza-config-manifest. Existing per-secret refs are left untouched (they keep
resolving). --rekey additionally copies each hat-* secret to a moza-* name
(non-destructive, verified). --dry-run writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from moza.backends import load_backend
from moza.config import deserialize_config

OLD_MANIFEST = "hat-config-manifest"
NEW_MANIFEST = "moza-config-manifest"


def old_config_path() -> Path:
    return Path.home() / ".config" / "hat" / "config.json"


def new_config_path() -> Path:
    return Path.home() / ".config" / "moza" / "config.json"


def load_old_raw() -> dict:
    p = old_config_path()
    if not p.exists():
        sys.exit(f"no old config at {p}")
    return json.loads(p.read_text())


def rewrite_templates(raw: dict) -> None:
    sn = raw.get("secret_naming") or {}
    for k, v in list(sn.items()):
        if isinstance(v, str) and v.startswith("hat-"):
            sn[k] = "moza-" + v[len("hat-"):]
    raw["secret_naming"] = sn


def write_new(raw: dict, *, force: bool, dry_run: bool) -> None:
    dst = new_config_path()
    if dst.exists() and not force:
        sys.exit(f"{dst} exists; pass --force to overwrite")
    if dry_run:
        print(f"[dry-run] would write {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(raw, indent=2))
    dst.chmod(0o600)
    print(f"wrote {dst}")


def migrate_manifest(raw: dict, *, dry_run: bool) -> None:
    sb = dict(raw.get("secrets_backend", {}))
    if sb.get("type") not in {"gcp_secret_manager", "oci_vault"}:
        print("local backend - no manifest to migrate")
        return
    cfg = deserialize_config(raw)
    backend = load_backend(cfg.secrets_backend)
    refs = backend.list(prefix=OLD_MANIFEST)
    if not refs:
        print("no old manifest found")
        return
    data = backend.get(refs[0])
    if dry_run:
        print(f"[dry-run] would re-push manifest as {NEW_MANIFEST}")
        return
    backend.put(NEW_MANIFEST, data)
    print(f"re-pushed manifest as {NEW_MANIFEST}")


def rekey_secrets(raw: dict, *, dry_run: bool) -> None:
    cfg = deserialize_config(raw)
    backend = load_backend(cfg.secrets_backend)

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.endswith("_ref") and isinstance(v, str) and "hat-" in v:
                    yield (obj, k, v)
                else:
                    yield from walk(v)
        elif isinstance(obj, list):
            for it in obj:
                yield from walk(it)

    for parent, key, ref in list(walk(raw.get("profiles", {}))):
        if ref.startswith("ocid1."):
            continue
        new_ref = ref.replace("hat-", "moza-")
        if dry_run:
            print(f"[dry-run] rekey {ref} -> {new_ref}")
            continue
        value = backend.get(ref)
        name = new_ref.split("/")[-1] if "/" in new_ref else new_ref
        put_ref = backend.put(name, value)
        assert backend.get(put_ref) == value, f"verify failed for {new_ref}"
        parent[key] = put_ref
        print(f"rekeyed {ref} -> {put_ref}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rekey", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = load_old_raw()
    rewrite_templates(raw)
    migrate_manifest(raw, dry_run=args.dry_run)
    if args.rekey:
        rekey_secrets(raw, dry_run=args.dry_run)
    write_new(raw, force=args.force, dry_run=args.dry_run)
    print("done" if not args.dry_run else "dry-run done")


if __name__ == "__main__":
    main()
