from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch fill the bottom area of image files with white."
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        help="Image file or folder containing images.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file or folder. Defaults to '<input>_white' for folders.",
    )
    parser.add_argument(
        "--top-percent",
        type=float,
        default=70.0,
        help="Start whitening at this percent of image height. Default: 70.",
    )
    parser.add_argument(
        "--top-px",
        type=int,
        help="Start whitening at this Y pixel instead of using --top-percent.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process images in subfolders too.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite input images. Use carefully.",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=95,
        help="JPEG/WebP output quality. Default: 95.",
    )
    return parser.parse_args()


def iter_images(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in IMAGE_EXTENSIONS else []

    pattern = "**/*" if recursive else "*"
    return sorted(
        file
        for file in path.glob(pattern)
        if file.is_file() and file.suffix.lower() in IMAGE_EXTENSIONS
    )


def default_output_path(input_path: Path) -> Path:
    if input_path.is_file():
        return input_path.with_name(f"{input_path.stem}_white{input_path.suffix}")
    return input_path.with_name(f"{input_path.name}_white")


def output_for_image(
    image_path: Path,
    input_path: Path,
    output_path: Path,
    overwrite: bool,
) -> Path:
    if overwrite:
        return image_path

    if input_path.is_file():
        return output_path

    relative_path = image_path.relative_to(input_path)
    return output_path / relative_path


def whiten_image(image_path: Path, output_path: Path, top_percent: float, top_px: int | None, quality: int) -> None:
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        width, height = image.size
        y_start = top_px if top_px is not None else round(height * top_percent / 100)
        y_start = max(0, min(height, y_start))

        draw = ImageDraw.Draw(image)
        draw.rectangle((0, y_start, width, height), fill=(255, 255, 255))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = output_path.suffix.lower()
        save_kwargs: dict[str, int] = {}
        if suffix in {".jpg", ".jpeg", ".webp"}:
            save_kwargs["quality"] = quality
        image.save(output_path, **save_kwargs)


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    input_path = args.input.resolve() if args.input else script_path.parent

    if not input_path.exists():
        print(f"Input does not exist: {input_path}")
        return 1

    output_path = args.output.resolve() if args.output else default_output_path(input_path).resolve()
    images = iter_images(input_path, args.recursive)
    images = [image for image in images if image.resolve() != script_path]

    if not images:
        print("No image files found.")
        return 1

    if args.overwrite:
        output_path = input_path

    for image_path in images:
        target_path = output_for_image(image_path, input_path, output_path, args.overwrite)
        whiten_image(image_path, target_path, args.top_percent, args.top_px, args.quality)
        print(f"{image_path} -> {target_path}")

    print(f"Done. Processed {len(images)} image(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
