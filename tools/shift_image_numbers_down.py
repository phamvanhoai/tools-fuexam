from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


DEFAULT_PREFIX = "HCM202 SU26 FE_"
DEFAULT_EXT = ".jpg"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rename numbered image files by subtracting from their number."
    )
    parser.add_argument(
        "folder",
        type=Path,
        nargs="?",
        help="Folder containing images. Defaults to the folder containing this tool.",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"Filename prefix before the number. Default: {DEFAULT_PREFIX!r}.",
    )
    parser.add_argument(
        "--ext",
        default=DEFAULT_EXT,
        help=f"Filename extension. Default: {DEFAULT_EXT!r}.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=21,
        help="Start renaming from this number. Default: 21.",
    )
    parser.add_argument(
        "--minus",
        type=int,
        default=1,
        help="Subtract this value from each matching number. Default: 1.",
    )
    parser.add_argument(
        "--digits",
        type=int,
        default=3,
        help="Number padding width. Default: 3.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be renamed without changing files.",
    )
    return parser.parse_args()


def backup_path_for(folder: Path) -> Path:
    base = folder / "_rename_backup"
    if not base.exists():
        return base

    index = 1
    while True:
        candidate = folder / f"_rename_backup_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def collect_renames(
    folder: Path,
    prefix: str,
    ext: str,
    start: int,
    minus: int,
    digits: int,
) -> list[tuple[Path, Path]]:
    extension = ext if ext.startswith(".") else f".{ext}"
    pattern = re.compile(rf"^{re.escape(prefix)}(\d{{{digits}}}){re.escape(extension)}$", re.IGNORECASE)
    renames: list[tuple[Path, Path]] = []

    for file in sorted(folder.iterdir()):
        if not file.is_file():
            continue

        match = pattern.match(file.name)
        if not match:
            continue

        number = int(match.group(1))
        if number < start:
            continue

        new_number = number - minus
        if new_number < 0:
            continue

        target = folder / f"{prefix}{new_number:0{digits}d}{extension}"
        if file.resolve() != target.resolve():
            renames.append((file, target))

    return renames


def run_rename(folder: Path, renames: list[tuple[Path, Path]], dry_run: bool) -> int:
    if not renames:
        print("No matching files found.")
        return 1

    sources = {source.resolve() for source, _ in renames}
    backup_dir = backup_path_for(folder)
    temp_paths: list[tuple[Path, Path]] = []

    print("Rename plan:")
    for source, target in renames:
        print(f"  {source.name} -> {target.name}")

    collisions = [
        target for _, target in renames
        if target.exists() and target.resolve() not in sources
    ]

    if collisions:
        print()
        print(f"Existing target files will be moved to backup folder: {backup_dir.name}")
        for target in collisions:
            print(f"  backup {target.name}")

    if dry_run:
        print()
        print("Dry run only. No files changed.")
        return 0

    if collisions:
        backup_dir.mkdir(parents=True, exist_ok=True)
        for target in collisions:
            shutil.move(str(target), str(backup_dir / target.name))

    for index, (source, _) in enumerate(renames):
        temp = folder / f".rename_tmp_{index:04d}_{source.name}"
        shutil.move(str(source), str(temp))
        temp_paths.append((temp, renames[index][1]))

    for temp, target in temp_paths:
        shutil.move(str(temp), str(target))

    print()
    print(f"Done. Renamed {len(renames)} file(s).")
    if collisions:
        print(f"Backed up {len(collisions)} existing file(s) to: {backup_dir}")
    return 0


def main() -> int:
    args = parse_args()
    folder = args.folder.resolve() if args.folder else Path(__file__).resolve().parent

    if not folder.exists() or not folder.is_dir():
        print(f"Folder does not exist: {folder}")
        return 1

    renames = collect_renames(
        folder=folder,
        prefix=args.prefix,
        ext=args.ext,
        start=args.start,
        minus=args.minus,
        digits=args.digits,
    )
    return run_rename(folder, renames, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
