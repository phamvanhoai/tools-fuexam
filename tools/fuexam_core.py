from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
NUMBERED_NAME = re.compile(r"^(.*?)(\d+)(\.[^.]+)$")


@dataclass(frozen=True)
class RenameItem:
    source: Path
    target: Path
    question_number: int


def clean_light_gray_watermarks(
    image: Image.Image,
    brightness_threshold: int = 205,
    color_tolerance: int = 3,
    brightness_ceiling: int = 255,
    preserve_long_lines: bool = True,
    preserve_text_edges: bool = True,
) -> Image.Image:
    """Turn nearly neutral-gray pixels in a brightness range white."""
    lower = max(0, min(255, int(brightness_threshold)))
    upper = max(0, min(255, int(brightness_ceiling)))
    lower, upper = min(lower, upper), max(lower, upper)
    tolerance = max(0, min(255, int(color_tolerance)))
    source = image.convert("RGB")
    red, green, blue = source.split()
    darkest = ImageChops.darker(red, ImageChops.darker(green, blue))
    lightest = ImageChops.lighter(red, ImageChops.lighter(green, blue))
    color_delta = ImageChops.subtract(lightest, darkest)
    # Pure white is already the desired background. Excluding it prevents the
    # long-line detector from treating the entire canvas as protected content.
    effective_upper = min(254, upper)
    bright_mask = darkest.point(lambda value: 255 if lower <= value <= effective_upper else 0)
    neutral_mask = color_delta.point(lambda value: 255 if value <= tolerance else 0)
    mask = ImageChops.multiply(bright_mask, neutral_mask)
    if preserve_text_edges:
        # JPEG anti-alias pixels around dark glyphs are often the same gray as a
        # watermark. Keep a narrow halo around dark content so text stays sharp.
        dark_content = darkest.point(lambda value: 255 if value <= 145 else 0)
        protected_text_edges = dark_content.filter(ImageFilter.MaxFilter(3))
        mask = ImageChops.subtract(mask, protected_text_edges)
    if preserve_long_lines and source.width >= 20 and source.height >= 20:
        # Borders and table rules often share the exact same gray as a watermark.
        # Require one long contiguous run; scattered watermark fragments on the
        # same row/column must not be mistaken for a frame line.
        values = mask.tobytes()
        protected = Image.new("L", source.size, 0)
        draw = ImageDraw.Draw(protected)
        minimum_horizontal = max(20, source.width // 4)
        for y in range(source.height):
            longest = run = 0
            row_start = y * source.width
            for x in range(source.width):
                if values[row_start + x]:
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
            if longest >= minimum_horizontal:
                draw.line((0, y, source.width - 1, y), fill=255, width=1)
        minimum_vertical = max(20, source.height // 4)
        for x in range(source.width):
            longest = run = 0
            for y in range(source.height):
                if values[y * source.width + x]:
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
            if longest >= minimum_vertical:
                draw.line((x, 0, x, source.height - 1), fill=255, width=1)
        protected = protected.filter(ImageFilter.MaxFilter(7))
        mask = ImageChops.subtract(mask, protected)
    white = Image.new("RGB", source.size, "white")
    return Image.composite(white, source, mask)


def _prepare_watermark_logo(
    logo: Image.Image,
    target_width: int,
    opacity_percent: int,
    color: tuple[int, int, int],
    angle: float = 0,
) -> Image.Image:
    source = logo.convert("RGBA")
    alpha = source.getchannel("A")
    content_box = alpha.getbbox()
    if content_box:
        source = source.crop(content_box)
        alpha = source.getchannel("A")
    target_width = max(1, int(target_width))
    target_height = max(1, round(source.height * target_width / source.width))
    alpha = alpha.resize((target_width, target_height), Image.Resampling.LANCZOS)
    opacity = max(0, min(100, int(opacity_percent))) / 100
    alpha = alpha.point(lambda value: round(value * opacity))
    tinted = Image.new("RGBA", (target_width, target_height), (*color, 0))
    tinted.putalpha(alpha)
    if angle:
        tinted = tinted.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    return tinted


def _watermark_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arialbd.ttf",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeuib.ttf",
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=max(8, size))
    return ImageFont.load_default()


def _prepare_watermark_text(
    text: str,
    font_size: int,
    opacity_percent: int,
    color: tuple[int, int, int],
    angle: float,
) -> Image.Image:
    font = _watermark_font(font_size)
    scratch = Image.new("L", (1, 1))
    box = ImageDraw.Draw(scratch).textbbox((0, 0), text, font=font)
    padding = max(4, font_size // 5)
    width = max(1, box[2] - box[0] + padding * 2)
    height = max(1, box[3] - box[1] + padding * 2)
    opacity = round(255 * max(0, min(100, opacity_percent)) / 100)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(
        (padding - box[0], padding - box[1]),
        text,
        font=font,
        fill=(*color, opacity),
    )
    if angle:
        layer = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    return layer


def apply_logo_watermark(
    image: Image.Image,
    logo: Image.Image,
    mode: str = "center_and_tile",
    opacity_percent: int = 10,
    center_scale_percent: int = 20,
    tile_text: str = "FUEXAM",
    tile_text_size_percent: int = 4,
    tile_angle: float = -25,
    spacing_percent: int = 8,
    color: tuple[int, int, int] = (128, 128, 128),
) -> Image.Image:
    """Overlay a logo at the center and/or customizable repeated text."""
    base = image.convert("RGBA")
    add_center = mode in {"center", "center_and_tile"}
    add_tiles = mode in {"tile", "center_and_tile"}
    center: Image.Image | None = None
    center_position = (0, 0)
    protected_center: tuple[int, int, int, int] | None = None

    if add_center:
        center_width = max(20, round(base.width * max(1, center_scale_percent) / 100))
        center = _prepare_watermark_logo(logo, center_width, opacity_percent, color)
        center_position = ((base.width - center.width) // 2, (base.height - center.height) // 2)
        clear_padding = max(8, round(base.width * 0.035))
        protected_center = (
            center_position[0] - clear_padding,
            center_position[1] - clear_padding,
            center_position[0] + center.width + clear_padding,
            center_position[1] + center.height + clear_padding,
        )

    if add_tiles:
        text = tile_text.strip()
        if not text:
            raise ValueError("Nội dung watermark lặp không được để trống.")
        font_size = max(8, round(base.height * max(1, tile_text_size_percent) / 100))
        tile = _prepare_watermark_text(text, font_size, opacity_percent, color, tile_angle)
        gap = max(8, round(base.width * max(0, spacing_percent) / 100))
        step_x = tile.width + gap
        step_y = tile.height + gap
        row = 0
        y = -tile.height // 2
        while y < base.height:
            x = -tile.width // 2 - (step_x // 2 if row % 2 else 0)
            while x < base.width:
                overlaps_center = (
                    protected_center is not None
                    and x < protected_center[2]
                    and x + tile.width > protected_center[0]
                    and y < protected_center[3]
                    and y + tile.height > protected_center[1]
                )
                if not overlaps_center:
                    base.alpha_composite(tile, (x, y))
                x += step_x
            y += step_y
            row += 1

    if center is not None:
        base.alpha_composite(center, center_position)

    return base.convert("RGB")


def list_images(folder: Path, recursive: bool = False) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        (p for p in folder.glob(pattern) if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda p: p.name.lower(),
    )


def infer_name_parts(path: Path) -> tuple[str, int, str]:
    match = NUMBERED_NAME.match(path.name)
    if not match:
        return f"{path.stem}_", 3, path.suffix
    prefix, number, extension = match.groups()
    return prefix, len(number), extension


def make_target(source: Path, question_number: int, prefix: str, digits: int, extension: str) -> Path:
    ext = extension if extension.startswith(".") else f".{extension}"
    return source.parent / f"{prefix}{question_number:0{digits}d}{ext}"


def validate_rename_items(items: list[RenameItem]) -> None:
    if not items:
        raise ValueError("Không có file nào để đổi tên.")
    targets: dict[str, Path] = {}
    for item in items:
        if item.question_number < 0:
            raise ValueError(f"Số câu không hợp lệ: {item.question_number}")
        key = str(item.target.resolve()).lower()
        if key in targets and targets[key] != item.source:
            raise ValueError(f"Nhiều ảnh cùng đổi thành {item.target.name}.")
        targets[key] = item.source


def unique_backup_folder(folder: Path) -> Path:
    base = folder / "_rename_backup"
    if not base.exists():
        return base
    index = 1
    while (candidate := folder / f"_rename_backup_{index}").exists():
        index += 1
    return candidate


def execute_safe_rename(items: list[RenameItem]) -> tuple[int, Path | None, int]:
    validate_rename_items(items)
    active = [item for item in items if item.source.resolve() != item.target.resolve()]
    if not active:
        return 0, None, 0

    source_keys = {str(item.source.resolve()).lower() for item in active}
    collisions: list[Path] = []
    seen: set[str] = set()
    for item in active:
        key = str(item.target.resolve()).lower()
        if item.target.exists() and key not in source_keys and key not in seen:
            collisions.append(item.target)
            seen.add(key)

    backup = unique_backup_folder(active[0].source.parent) if collisions else None
    if backup:
        backup.mkdir(parents=True)
        for path in collisions:
            shutil.move(str(path), str(backup / path.name))

    staged: list[tuple[Path, Path, Path]] = []
    try:
        for item in active:
            temp = item.source.with_name(f".fuexam_tmp_{uuid.uuid4().hex}{item.source.suffix}")
            shutil.move(str(item.source), str(temp))
            staged.append((item.source, temp, item.target))
        for _, temp, target in staged:
            shutil.move(str(temp), str(target))
    except Exception:
        for original, temp, target in reversed(staged):
            if target.exists() and not original.exists():
                shutil.move(str(target), str(original))
            elif temp.exists() and not original.exists():
                shutil.move(str(temp), str(original))
        if backup:
            for path in collisions:
                saved = backup / path.name
                if saved.exists() and not path.exists():
                    shutil.move(str(saved), str(path))
        raise
    return len(active), backup, len(collisions)


def extract_first_json_integer(text: str) -> int:
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            for key in ("question_number", "number", "question"):
                if key in value:
                    return int(value[key])
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    match = re.search(r"(?:question(?:_number)?|câu|number)\D{0,20}(\d{1,4})", text, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(\d{1,4})\b", text)
    if not match:
        raise ValueError(f"AI không trả về số câu: {text[:120]}")
    return int(match.group(1))


def get_ollama_models(endpoint: str = "http://127.0.0.1:11434", timeout: int = 3) -> list[str]:
    try:
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/api/tags", timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Không kết nối được Ollama tại {endpoint}: {exc}") from exc
    return [str(model.get("name", "")) for model in result.get("models", []) if model.get("name")]


def find_ollama_executable() -> Path | None:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return candidate
    return None


def find_tesseract_executable() -> Path | None:
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _question_header(image_path: Path) -> Image.Image:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    header_height = max(1, round(image.height * 0.28))
    image = image.crop((0, 0, image.width, header_height))
    if image.width > 1600:
        height = max(1, round(image.height * 1600 / image.width))
        image = image.resize((1600, height), Image.Resampling.LANCZOS)
    return image


def detect_question_with_tesseract(image_path: Path, timeout: int = 30) -> int:
    executable = find_tesseract_executable()
    if executable is None:
        raise RuntimeError(
            "Chưa tìm thấy Tesseract OCR. Hãy cài Tesseract OCR cho Windows rồi mở lại tool."
        )
    image = _question_header(image_path)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    try:
        result = subprocess.run(
            [str(executable), "stdin", "stdout", "-l", "eng", "--psm", "6"],
            input=buffer.getvalue(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Tesseract nhận diện quá thời gian cho phép.") from exc
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Tesseract gặp lỗi: {error}")
    text = result.stdout.decode("utf-8", errors="replace")
    # Vietnamese headers are commonly rendered as "Câu 20". With the English
    # Tesseract language pack the accent is usually dropped and becomes
    # "Cau 20", so accept both forms in addition to the English "Question 20".
    match = re.search(
        r"\b(?:multiple\s+choice\s+question|question|c[aâ]u)\s*[:#.-]?\s*(\d{1,4})\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "Tesseract không tìm thấy 'Câu/Question + số'. "
            f"Nội dung đọc được: {text.strip()[:100]}"
        )
    return int(match.group(1))


def _normalize_ocr_text(value: str) -> str:
    value = value.lower().replace("đ", "d")
    value = unicodedata.normalize("NFD", value)
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def locate_text_lines_with_tesseract(
    image_path: Path,
    query: str,
    timeout: int = 45,
) -> list[tuple[int, int, int, int, str]]:
    """Return full OCR line boxes containing query as (left, top, right, bottom, text)."""
    executable = find_tesseract_executable()
    if executable is None:
        raise RuntimeError("Chưa tìm thấy Tesseract OCR. Hãy cài Tesseract OCR cho Windows rồi mở lại tool.")
    normalized_query = _normalize_ocr_text(query)
    if not normalized_query:
        raise ValueError("Cụm chữ cần tìm không được để trống.")
    try:
        result = subprocess.run(
            [str(executable), str(image_path), "stdout", "-l", "eng", "--psm", "6", "tsv"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Tesseract tìm chữ quá thời gian cho phép.") from exc
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Tesseract gặp lỗi: {error}")

    decoded = result.stdout.decode("utf-8", errors="replace")
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in csv.DictReader(io.StringIO(decoded), delimiter="\t"):
        if row.get("level") != "5" or not row.get("text", "").strip():
            continue
        key = (row.get("page_num", ""), row.get("block_num", ""), row.get("par_num", ""), row.get("line_num", ""))
        groups.setdefault(key, []).append(row)

    matches: list[tuple[int, int, int, int, str]] = []
    for words in groups.values():
        line_text = " ".join(word["text"].strip() for word in words)
        if normalized_query not in _normalize_ocr_text(line_text):
            continue
        left = min(int(word["left"]) for word in words)
        top = min(int(word["top"]) for word in words)
        right = max(int(word["left"]) + int(word["width"]) for word in words)
        bottom = max(int(word["top"]) + int(word["height"]) for word in words)
        matches.append((left, top, right, bottom, line_text))
    return matches


def ensure_ollama_server(endpoint: str = "http://127.0.0.1:11434") -> list[str]:
    try:
        return get_ollama_models(endpoint)
    except RuntimeError:
        pass
    executable = find_ollama_executable()
    if executable is None:
        raise RuntimeError(
            "Chưa tìm thấy Ollama trên máy. Hãy cài Ollama, mở ứng dụng Ollama, "
            "sau đó tải một model vision bằng lệnh: ollama pull qwen2.5vl:3b"
        )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(executable), "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    last_error: Exception | None = None
    for _ in range(10):
        time.sleep(0.5)
        try:
            return get_ollama_models(endpoint)
        except RuntimeError as exc:
            last_error = exc
    raise RuntimeError(f"Đã thử khởi động Ollama nhưng server chưa sẵn sàng: {last_error}")


def unload_ollama_model(
    model: str,
    endpoint: str = "http://127.0.0.1:11434",
    timeout: int = 30,
) -> None:
    payload = {"model": model, "stream": False, "keep_alive": 0}
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Không thể giải phóng model {model}: {exc}") from exc
    if "error" in result:
        raise RuntimeError(str(result["error"]))


def detect_question_with_ollama(
    image_path: Path,
    model: str,
    endpoint: str = "http://127.0.0.1:11434",
    timeout: int = 120,
) -> int:
    # The question number is in the header. Sending only that area makes local
    # vision inference substantially faster and avoids distracting numbers in
    # the question body and answers.
    image = _question_header(image_path)
    with image:
        if image.width > 1024:
            new_height = max(1, round(image.height * 1024 / image.width))
            image = image.resize((1024, new_height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
    payload = {
        "model": model,
        "stream": False,
        "prompt": (
            "Read the question number displayed in this exam screenshot. "
            "Return JSON only in this exact format: {\"question_number\": 7}. "
            "Do not use numbers from the filename, course code, answer choices, or question text."
        ),
        "images": [base64.b64encode(buffer.getvalue()).decode("ascii")],
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Không kết nối được Ollama: {exc}") from exc
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    return extract_first_json_integer(str(result.get("response", "")))
