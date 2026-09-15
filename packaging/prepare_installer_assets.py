"""Copy the user's existing icon and logo unchanged into installer assets."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil


def prepare(source_directory: Path) -> list[tuple[Path, str]]:
    destination = Path(__file__).resolve().parent / "assets"
    sources = [source_directory / "S4_Studio.ico", source_directory / "S4_Studio_icon.png"]
    expected_signatures = [b"\x00\x00\x01\x00", b"\x89PNG\r\n\x1a\n"]
    for source, signature in zip(sources, expected_signatures):
        with source.open("rb") as stream:
            if stream.read(len(signature)) != signature:
                raise ValueError(f"Unexpected image format: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in sources:
        target = destination / source.name
        shutil.copyfile(source, target)
        source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest() != source_digest:
            raise OSError(f"Copied icon failed verification: {target}")
        copied.append((target, source_digest))
    return copied


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-directory", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    for target, digest in prepare(args.source_directory.resolve()):
        print(f"{target.name}: SHA256 {digest}")
