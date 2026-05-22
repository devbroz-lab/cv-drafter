#!/usr/bin/env python3
"""
Rename pipeline diagnostic fix labels per FIX_LABEL_RENAME_MAPPING.md.

Longest keys first. Excludes FIELD_EDITOR_SKIP_FIXES.md, FIELD_EDITOR_MISMATCH_FIXES.md,
and RENDERER_ISSUES.md by default.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Longest-first (critical for Fix FF-B before Fix FF, Fix 5b before Fix 5, etc.)
REPLACEMENTS: list[tuple[str, str]] = [
    ("Fix FF-B", "R7-D"),
    ("Fix FF-A", "R7-C"),
    ("Fix II-B", "R7-I"),
    ("Fix II-A", "R7-H"),
    ("Fix PP-B", "R7.5-D"),
    ("Fix PP-A", "R7.5-C"),
    ("Fix QQ-B", "R7.5-F"),
    ("Fix QQ-A", "R7.5-E"),
    ("Fix R7-5", "R7-G"),
    ("Fix 4b", "R5-A"),
    ("Fix 5b", "R5-D"),
    ("Fix AA", "R6-F"),
    ("Fix AB", "R6-G"),
    ("Fix DD", "R7-A"),
    ("Fix EE", "R7-B"),
    ("Fix GG", "R7-E"),
    ("Fix HH", "R7-F"),
    ("Fix JJ", "R7-J"),
    ("Fix KK", "R7-K"),
    ("Fix LL", "R7-L"),
    ("Fix MM", "R7-M"),
    ("Fix NN", "R7.5-A"),
    ("Fix OO", "R7.5-B"),
    ("Fix RR", "R7.5-G"),
    ("Fix SS", "R7.5-H"),
    ("Fix TT", "R7.5-I"),
    ("Fix U", "R5-E"),
    ("Fix V", "R6-A"),
    ("Fix W", "R6-B"),
    ("Fix X", "R6-C"),
    ("Fix Y", "R6-D"),
    ("Fix Z", "R6-E"),
    ("Fix N", "R4-A"),
    ("Fix O", "R4-B"),
    ("Fix P", "R4-C"),
    ("Fix Q", "R4-D"),
    ("Fix R", "R4-E"),
    # Fix 4 and Fix 2 after Fix 4b to avoid partial matches
    ("Fix 4", "R5-B"),
    ("Fix 2", "R5-C"),
]

DEFAULT_EXCLUDES = {
    "FIELD_EDITOR_SKIP_FIXES.md",
    "FIELD_EDITOR_MISMATCH_FIXES.md",
    "RENDERER_ISSUES.md",
    "FIX_LABEL_RENAME_MAPPING.md",
    "rename_fix_labels.py",
}

DEFAULT_GLOBS = [
    "additions",
    "markdowns",
    "pipeline",
    "templates",
    "tests",
    "api",
]


def should_process(path: Path, excludes: set[str]) -> bool:
    if path.name in excludes:
        return False
    if path.suffix not in {".md", ".py"}:
        return False
    return True


def collect_files(paths: list[Path], excludes: set[str]) -> list[Path]:
    files: list[Path] = []
    for base in paths:
        if base.is_file():
            if should_process(base, excludes):
                files.append(base)
            continue
        for p in base.rglob("*"):
            if p.is_file() and should_process(p, excludes):
                files.append(p)
    if (ROOT / "models.py").exists() and should_process(ROOT / "models.py", excludes):
        files.append(ROOT / "models.py")
    return sorted(set(files))


# Single-letter Fix R/N/O/P/Q/U/V/W/X/Y/Z must not match inside R7.5-* or Fix R7-5.
_BOUNDARY_PREFIXES = ("R7.", "Fix R7", "R4-", "R5-", "R6-", "R7-", "R8-")


def _replace_one(text: str, old: str, new: str) -> tuple[str, int]:
    if old in ("Fix R", "Fix N", "Fix O", "Fix P", "Fix Q", "Fix U", "Fix V",
               "Fix W", "Fix X", "Fix Y", "Fix Z", "Fix 2", "Fix 4"):
        pattern = re.compile(rf"(?<!Fix R7)(?<!R7\.)(?<![A-Z0-9-]){re.escape(old)}(?![0-9A-Za-z.-])")
        count = 0

        def repl(m: re.Match[str]) -> str:
            nonlocal count
            start = m.start()
            for prefix in _BOUNDARY_PREFIXES:
                if text[max(0, start - len(prefix)) : start].endswith(
                    prefix.replace("Fix R7", "Fix R7")
                ):
                    return m.group(0)
            # Check Fix R7 / R7. prefixes explicitly
            before = text[max(0, start - 8) : start]
            if "Fix R7" in before or before.endswith("R7."):
                return m.group(0)
            count += 1
            return new

        updated = pattern.sub(repl, text)
        return updated, count

    if old in text:
        n = text.count(old)
        return text.replace(old, new), n
    return text, 0


def apply_replacements(text: str) -> tuple[str, int]:
    count = 0
    for old, new in REPLACEMENTS:
        text, n = _replace_one(text, old, new)
        count += n
    return text, count


def process_file(path: Path, dry_run: bool) -> int:
    original = path.read_text(encoding="utf-8")
    updated, count = apply_replacements(original)
    if count and not dry_run:
        path.write_text(updated, encoding="utf-8", newline="\n")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Rename pipeline fix labels")
    parser.add_argument("--dry-run", action="store_true", help="Report changes only")
    parser.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="Paths relative to cv-drafter root (default: additions markdowns pipeline ...)",
    )
    args = parser.parse_args()

    rel_paths = args.paths or DEFAULT_GLOBS
    bases = [ROOT / p for p in rel_paths]
    excludes = set(DEFAULT_EXCLUDES)
    files = collect_files(bases, excludes)

    total = 0
    changed_files = 0
    for f in files:
        n = process_file(f, args.dry_run)
        if n:
            changed_files += 1
            total += n
            rel = f.relative_to(ROOT)
            mode = "would change" if args.dry_run else "changed"
            print(f"  {mode}: {rel} ({n} replacements)")

    print(f"\n{'Would replace' if args.dry_run else 'Replaced'} {total} occurrences in {changed_files} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
