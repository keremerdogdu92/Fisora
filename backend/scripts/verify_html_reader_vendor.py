# File: backend/scripts/verify_html_reader_vendor.py
# Summary: Verifies vendored HTML reader runtime files against the audited frozen release and integration bridge hashes.
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys


EXPECTED = {
    "package.json": "9770a1cf4ea1b3471a502fb7ae4a5723e27aca2e36976feac3943dbaf9c4f41a",
    "package-lock.json": "d210082f1b7c69a55f4bf212686d44cf7635dc97541d713dcb55ddee758ad618",
    "src/html-source-reader.mjs": "9bc0798f4aab88f0ba8ab1c030111dfad57c744aca4009dce16f46a90a9088fa",
    "src/index.mjs": "929d1dc9a39ceebc16127d158516e03cdd9446248884c9e9619c024eacf4baa3",
    "src/snapshot-contract.mjs": "2e4c8f04d8ef95004b7f1ff7e4bf785c14002e5466eab4daf7b1e78a3eaa2b51",
    "integration/fisora-html-reader-bridge.mjs": "3f4e0859153ec3bbf81e07ea370c54c3eef32e59f057992bea69a07c24bf28a4",
    "integration/fisora-html-reader-jsonl-worker.mjs": "011bc84f12a7018c5beed47b6da3595be2ffb6b9e5a551cfecf053ec2954882f",
}


def verify(root: Path) -> list[str]:
    failures: list[str] = []
    for relative, expected in EXPECTED.items():
        path = root / relative
        if not path.is_file():
            failures.append(f"missing:{relative}")
            continue
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            failures.append(f"hash_mismatch:{relative}:{actual}")
    return failures


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/vendor/fisora-html-source-reader")
    failures = verify(root)
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print(f"html_reader_vendor_verified files={len(EXPECTED)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
