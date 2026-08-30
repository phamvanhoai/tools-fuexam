from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
NUMBERED_NAME = re.compile(r"^(.*?)(\d+)(\.[^.]+)$")


@dataclass(frozen=True)
class RenameItem:
    source: Path
    target: Path
    question_number: int


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
