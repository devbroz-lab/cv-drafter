"""
Dev 2 test harness — run this to see the extractor output for any CV file.

Usage:
    python scripts/test_extraction.py tests/sample_files/sample_giz.docx giz
    python scripts/test_extraction.py tests/sample_files/sample_wb.docx world_bank

Drop sample CV files into tests/sample_files/ first.
Output is printed to stdout and also saved to runs/dev_test/extraction.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running from repo root without installing
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.extractor import extract_text


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_extraction.py <cv_file> <giz|world_bank>")
        sys.exit(1)

    cv_path = Path(sys.argv[1])
    target_format = sys.argv[2]

    if not cv_path.exists():
        print(f"File not found: {cv_path}")
        sys.exit(1)

    file_bytes = cv_path.read_bytes()
    source_text = extract_text(cv_path.name, file_bytes)

    output = {
        "file": str(cv_path),
        "target_format": target_format,
        "source_text": source_text,
    }

    out_dir = Path("runs/dev_test")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "extraction.json"
    out_file.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print("=" * 60)
    print(source_text)
    print("=" * 60)
    print(f"\nSaved to: {out_file}")
    print(f"Lines: {len(source_text.splitlines())}")


if __name__ == "__main__":
    main()
