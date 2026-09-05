from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageColor, ImageDraw, ImageTk

from fuexam_core import (
    RenameItem,
    detect_question_with_ollama,
    detect_question_with_tesseract,
    execute_safe_rename,
    ensure_ollama_server,
    infer_name_parts,
    list_images,
    locate_text_lines_with_tesseract,
    make_target,
    unload_ollama_model,
    validate_rename_items,
)


class FUExamApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FUExam Image Tools")
        self.geometry("1120x720")
        self.minsize(900, 600)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.rows: dict[str, dict[str, object]] = {}
        self.detecting = False
        self._build()
        self.after(100, self._drain_events)

    def _build(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        self.rename_tab = ttk.Frame(notebook, padding=10)
        self.white_tab = ttk.Frame(notebook, padding=10)
        self.shift_tab = ttk.Frame(notebook, padding=10)
        self.prefix_tab = ttk.Frame(notebook, padding=10)
        self.crop_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.rename_tab, text="AI đổi tên theo số câu")
        notebook.add(self.white_tab, text="Tô màu vùng ảnh")
        notebook.add(self.shift_tab, text="Dịch số thứ tự")
        notebook.add(self.prefix_tab, text="Đổi prefix tên file")
        notebook.add(self.crop_tab, text="Cắt ảnh dài")
        self._build_rename_tab()
        self._build_white_tab()
        self._build_shift_tab()
        self._build_prefix_tab()
        self._build_crop_tab()
        self.status = tk.StringVar(value="Sẵn sàng")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=12, pady=(0, 8))

    def _folder_picker(self, parent: ttk.Frame, variable: tk.StringVar, row: int) -> None:
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(parent, text="Chọn thư mục", command=lambda: self._pick_folder(variable)).grid(row=row, column=2)

    @staticmethod
    def _pick_folder(variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(initialdir=variable.get() or None)
        if selected:
            variable.set(selected)

    def _build_rename_tab(self) -> None:
        tab = self.rename_tab
        tab.columnconfigure(1, weight=1)
        self.rename_folder = tk.StringVar()
        ttk.Label(tab, text="Thư mục ảnh:").grid(row=0, column=0, sticky="w")
        self._folder_picker(tab, self.rename_folder, 0)

        options = ttk.Frame(tab)
        options.grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)
        self.ollama_model = tk.StringVar(value="qwen2.5vl:3b")
        self.ollama_url = tk.StringVar(value="http://127.0.0.1:11434")
        self.ocr_engine = tk.StringVar(value="Tesseract (nhẹ, nhanh)")
        self.rename_prefix = tk.StringVar()
        self.rename_digits = tk.IntVar(value=3)
        self.rename_ext = tk.StringVar(value=".jpg")
        ttk.Label(options, text="Nhận diện:").pack(side="left")
        ttk.Combobox(
            options,
            textvariable=self.ocr_engine,
            values=("Tesseract (nhẹ, nhanh)", "Ollama Vision AI"),
            state="readonly",
            width=23,
        ).pack(side="left", padx=(4, 12))
        ttk.Label(options, text="Model Ollama:").pack(side="left")
        ttk.Entry(options, textvariable=self.ollama_model, width=18).pack(side="left", padx=(4, 12))
        ttk.Label(options, text="URL:").pack(side="left")
        ttk.Entry(options, textvariable=self.ollama_url, width=28).pack(side="left", padx=(4, 12))
        naming_options = ttk.Frame(tab)
        naming_options.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Label(naming_options, text="Tên mới — Prefix:").pack(side="left")
        ttk.Entry(naming_options, textvariable=self.rename_prefix, width=28).pack(side="left", padx=(4, 12))
        ttk.Label(naming_options, text="Số chữ số:").pack(side="left")
        ttk.Spinbox(naming_options, from_=1, to=8, textvariable=self.rename_digits, width=4).pack(side="left", padx=4)
        ttk.Label(naming_options, text="Đuôi:").pack(side="left")
        ttk.Entry(naming_options, textvariable=self.rename_ext, width=7).pack(side="left", padx=4)

        self.auto_unload_model = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            tab,
            text="Tự giải phóng model khỏi RAM/VRAM sau khi nhận diện",
            variable=self.auto_unload_model,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 8))

        buttons = ttk.Frame(tab)
        buttons.grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Button(buttons, text="1. Nạp ảnh", command=self.load_rename_images).pack(side="left")
        ttk.Button(buttons, text="Kiểm tra AI", command=self.check_ai).pack(side="left", padx=(6, 0))
        self.detect_button = ttk.Button(buttons, text="2. AI nhận diện tất cả", command=self.detect_all)
        self.detect_button.pack(side="left", padx=6)
        ttk.Button(buttons, text="Sửa số dòng chọn", command=self.edit_selected_number).pack(side="left")
        ttk.Button(buttons, text="3. Xem trước tên mới", command=self.preview_targets).pack(side="left", padx=6)
        ttk.Button(buttons, text="4. Thực hiện đổi tên", command=self.apply_rename).pack(side="left")

        columns = ("source", "question", "target", "state")
        self.rename_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
        for key, title, width in (
            ("source", "Tên hiện tại", 310), ("question", "Số câu", 90),
            ("target", "Tên mới", 310), ("state", "Trạng thái", 260),
        ):
            self.rename_tree.heading(key, text=title)
            self.rename_tree.column(key, width=width, anchor="w")
        self.rename_tree.grid(row=5, column=0, columnspan=3, sticky="nsew")
        tab.rowconfigure(5, weight=1)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.rename_tree.yview)
        scrollbar.grid(row=5, column=3, sticky="ns")
        self.rename_tree.configure(yscrollcommand=scrollbar.set)
        self.rename_tree.bind("<Double-1>", lambda _event: self.edit_selected_number())

    def load_rename_images(self) -> None:
        folder = Path(self.rename_folder.get())
        if not folder.is_dir():
            messagebox.showerror("Lỗi", "Hãy chọn thư mục ảnh hợp lệ.")
            return
        files = list_images(folder)
        self.rename_tree.delete(*self.rename_tree.get_children())
        self.rows.clear()
        if files:
            prefix, digits, ext = infer_name_parts(files[0])
            self.rename_prefix.set(prefix)
            self.rename_digits.set(digits)
            self.rename_ext.set(ext)
        for index, path in enumerate(files):
            iid = str(index)
            self.rows[iid] = {"source": path, "number": None, "target": None}
            self.rename_tree.insert("", "end", iid=iid, values=(path.name, "", "", "Chưa nhận diện"))
        self.status.set(f"Đã nạp {len(files)} ảnh.")

    def detect_all(self) -> None:
        if self.detecting:
            messagebox.showinfo("AI đang chạy", "AI đang nhận diện. Hãy chờ tiến trình hiện tại hoàn tất.")
            return
        if not self.rows:
            self.load_rename_images()
        if not self.rows:
            return
        if self.ocr_engine.get().startswith("Tesseract"):
            self.detecting = True
            self.detect_button.configure(state="disabled")
            self.status.set("Tesseract đang nhận diện...")
            threading.Thread(target=self._detect_tesseract_worker, daemon=True).start()
            return
        model = self.ollama_model.get().strip()
        if not model:
            messagebox.showerror("Lỗi", "Hãy nhập tên model vision của Ollama.")
            return
        self.detecting = True
        self.detect_button.configure(state="disabled")
        self.status.set("Đang kiểm tra và khởi động Ollama...")
        threading.Thread(target=self._prepare_ai_worker, args=(model, self.ollama_url.get()), daemon=True).start()

    def _detect_tesseract_worker(self) -> None:
        total = len(self.rows)
        fatal_error = None
        for position, (iid, row) in enumerate(list(self.rows.items()), 1):
            self.events.put(("detect_started_tesseract", (iid, position, total)))
            try:
                number = detect_question_with_tesseract(row["source"])  # type: ignore[arg-type]
                self.events.put(("detected", (iid, number, f"Tesseract ({position}/{total})")))
            except Exception as exc:
                self.events.put(("detect_error", (iid, str(exc), position, total)))
                if position == 1 and "Chưa tìm thấy Tesseract" in str(exc):
                    fatal_error = str(exc)
                    break
        self.events.put(("tesseract_done", fatal_error))

    def check_ai(self) -> None:
        self.status.set("Đang kiểm tra Ollama...")
        threading.Thread(target=self._check_ai_worker, args=(self.ollama_url.get(),), daemon=True).start()

    def _check_ai_worker(self, endpoint: str) -> None:
        try:
            models = ensure_ollama_server(endpoint)
            text = ", ".join(models) if models else "chưa có model nào"
            self.events.put(("ai_check_ok", text))
        except Exception as exc:
            self.events.put(("ai_check_error", str(exc)))

    def _prepare_ai_worker(self, model: str, endpoint: str) -> None:
        try:
            models = ensure_ollama_server(endpoint)
        except Exception as exc:
            self.events.put(("ai_check_error", str(exc)))
            return
        available = {name.lower() for name in models}
        if model.lower() not in available:
            self.events.put(("ai_check_error", f"Ollama đang chạy nhưng chưa có model '{model}'. Mở PowerShell và chạy: ollama pull {model}"))
            return
        self.events.put(("ai_ready", (model, endpoint)))

    def _detect_worker(self, model: str, endpoint: str, auto_unload: bool) -> None:
        total = len(self.rows)
        unload_error = None
        try:
            for position, (iid, row) in enumerate(list(self.rows.items()), 1):
                self.events.put(("detect_started", (iid, position, total)))
                try:
                    number = detect_question_with_ollama(row["source"], model, endpoint)  # type: ignore[arg-type]
                    self.events.put(("detected", (iid, number, f"Đã nhận diện ({position}/{total})")))
                except Exception as exc:
                    self.events.put(("detect_error", (iid, str(exc), position, total)))
        finally:
            if auto_unload:
                self.events.put(("unload_started", model))
                try:
                    unload_ollama_model(model, endpoint)
                except Exception as exc:
                    unload_error = str(exc)
            self.events.put(("detect_done", (auto_unload, unload_error)))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "detected":
                    iid, number, state = payload  # type: ignore[misc]
                    self.rows[iid]["number"] = number
                    row = self.rename_tree.item(iid, "values")
                    self.rename_tree.item(iid, values=(row[0], number, row[2], state))
                elif kind == "detect_started":
                    iid, pos, total = payload  # type: ignore[misc]
                    row = self.rename_tree.item(iid, "values")
                    self.rename_tree.item(iid, values=(row[0], row[1], row[2], f"Đang nhận diện ({pos}/{total})..."))
                    self.rename_tree.see(iid)
                    self.status.set(f"AI đang đọc ảnh {pos}/{total}. Lần đầu tải model có thể mất 20–60 giây.")
                elif kind == "detect_started_tesseract":
                    iid, pos, total = payload  # type: ignore[misc]
                    row = self.rename_tree.item(iid, "values")
                    self.rename_tree.item(iid, values=(row[0], row[1], row[2], f"Tesseract đang đọc ({pos}/{total})..."))
                    self.rename_tree.see(iid)
                    self.status.set(f"Tesseract đang đọc ảnh {pos}/{total}...")
                elif kind == "detect_error":
                    iid, error, pos, total = payload  # type: ignore[misc]
                    row = self.rename_tree.item(iid, "values")
                    self.rename_tree.item(iid, values=(row[0], row[1], row[2], f"Lỗi: {error}"))
                    self.status.set(f"Đang nhận diện {pos}/{total}")
                elif kind == "detect_done":
                    self.detecting = False
                    self.detect_button.configure(state="normal")
                    self.preview_targets()
                    auto_unload, unload_error = payload  # type: ignore[misc]
                    if unload_error:
                        self.status.set(f"Nhận diện xong nhưng chưa giải phóng được model: {unload_error}")
                        messagebox.showwarning("Cảnh báo", str(unload_error))
                    elif auto_unload:
                        self.status.set("Nhận diện xong; model đã được giải phóng. Hãy kiểm tra kết quả.")
                    else:
                        self.status.set("Nhận diện xong. Model vẫn được giữ theo lựa chọn của bạn.")
                elif kind == "tesseract_done":
                    self.detecting = False
                    self.detect_button.configure(state="normal")
                    self.preview_targets()
                    if payload:
                        self.status.set("Tesseract chưa được cài đặt.")
                        messagebox.showerror("Thiếu Tesseract OCR", str(payload))
                    else:
                        self.status.set("Tesseract nhận diện xong. Hãy kiểm tra kết quả.")
                elif kind == "unload_started":
                    self.status.set(f"Đã nhận diện xong. Đang giải phóng model {payload} khỏi RAM/VRAM...")
                elif kind == "ai_ready":
                    model, endpoint = payload  # type: ignore[misc]
                    self.status.set("AI local đang nhận diện...")
                    threading.Thread(
                        target=self._detect_worker,
                        args=(model, endpoint, self.auto_unload_model.get()),
                        daemon=True,
                    ).start()
                elif kind == "ai_check_ok":
                    self.status.set(f"Ollama hoạt động. Model đã cài: {payload}")
                    messagebox.showinfo("AI local", f"Kết nối Ollama thành công.\nModel đã cài: {payload}")
                elif kind == "ai_check_error":
                    self.detecting = False
                    self.detect_button.configure(state="normal")
                    self.status.set("AI local chưa sẵn sàng.")
                    messagebox.showerror("AI local chưa sẵn sàng", str(payload))
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def edit_selected_number(self) -> None:
        selected = self.rename_tree.selection()
        if not selected:
            return
        iid = selected[0]
        dialog = tk.Toplevel(self)
        dialog.title("Sửa số câu")
        dialog.transient(self)
        dialog.grab_set()
        value = tk.StringVar(value=str(self.rows[iid]["number"] or ""))
        ttk.Label(dialog, text=self.rows[iid]["source"].name).pack(padx=18, pady=(14, 6))  # type: ignore[union-attr]
        entry = ttk.Entry(dialog, textvariable=value, width=15)
        entry.pack(padx=18, pady=6)
        entry.focus_set()

        def save() -> None:
            try:
                number = int(value.get())
                if number < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Lỗi", "Số câu phải là số nguyên không âm.", parent=dialog)
                return
            self.rows[iid]["number"] = number
            row = self.rename_tree.item(iid, "values")
            self.rename_tree.item(iid, values=(row[0], number, row[2], "Đã sửa thủ công"))
            dialog.destroy()
            self.preview_targets()

        ttk.Button(dialog, text="Lưu", command=save).pack(pady=(4, 14))
        dialog.bind("<Return>", lambda _event: save())

    def _rename_items(self) -> list[RenameItem]:
        items = []
        for row in self.rows.values():
            if row["number"] is None:
                continue
            target = make_target(
                row["source"], int(row["number"]), self.rename_prefix.get(),  # type: ignore[arg-type]
                self.rename_digits.get(), self.rename_ext.get(),
            )
            row["target"] = target
            items.append(RenameItem(row["source"], target, int(row["number"])))  # type: ignore[arg-type]
        return items

    def preview_targets(self) -> None:
        try:
            items = self._rename_items()
            validate_rename_items(items)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        item_by_source = {item.source: item for item in items}
        sources = {item.source.resolve() for item in items}
        for iid, data in self.rows.items():
            source = data["source"]
            item = item_by_source.get(source)
            if not item:
                values = self.rename_tree.item(iid, "values")
                self.rename_tree.item(iid, values=(values[0], values[1], "", "Thiếu số câu"))
                continue
            if item.source.resolve() == item.target.resolve():
                state = "Tên đã đúng"
            elif item.target.exists() and item.target.resolve() not in sources:
                state = "Trùng file cũ → sẽ backup"
            else:
                state = "Sẵn sàng"
            self.rename_tree.item(iid, values=(item.source.name, item.question_number, item.target.name, state))
        self.status.set(f"Đã lập kế hoạch cho {len(items)}/{len(self.rows)} ảnh.")

    def apply_rename(self) -> None:
        try:
            items = self._rename_items()
            validate_rename_items(items)
            if len(items) != len(self.rows):
                raise ValueError("Vẫn còn ảnh chưa có số câu.")
        except ValueError as exc:
            messagebox.showerror("Không thể đổi tên", str(exc))
            return
        if not messagebox.askyesno("Xác nhận", f"Đổi tên {len(items)} ảnh theo bảng xem trước?"):
            return
        try:
            count, backup, collision_count = execute_safe_rename(items)
        except Exception as exc:
            messagebox.showerror("Đổi tên thất bại", str(exc))
            return
        detail = f"Đã đổi tên {count} file."
        if backup:
            detail += f"\nĐã đưa {collision_count} file trùng vào:\n{backup}"
        messagebox.showinfo("Hoàn tất", detail)
        self.load_rename_images()

    def _build_white_tab(self) -> None:
        tab = self.white_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(5, weight=1)
        self.white_input = tk.StringVar()
        self.white_output = tk.StringVar()
        self.white_recursive = tk.BooleanVar(value=False)
        self.paint_color = tk.StringVar(value="#FFFFFF")
        self.paint_regions: list[tuple[float, float, float, float, str]] = [(0.0, 0.70, 1.0, 1.0, "#FFFFFF")]
        self.paint_region: tuple[float, float, float, float] | None = None
        self.paint_default_region = True
        self.paint_mode = tk.StringVar(value="Vùng đánh dấu thủ công")
        self.follow_text = tk.StringVar(value="Đáp án tham khảo")
        self.follow_padding = tk.IntVar(value=12)
        self.paint_preview_image: Image.Image | None = None
        self.paint_preview_photo: ImageTk.PhotoImage | None = None
        self.paint_preview_path: Path | None = None
        self.paint_display_box = (0, 0, 1, 1)
        self.paint_drag_start: tuple[int, int] | None = None
        self.paint_eyedropper = False
        ttk.Label(tab, text="Thư mục nguồn:").grid(row=0, column=0, sticky="w", pady=5)
        self._folder_picker(tab, self.white_input, 0)
        ttk.Label(tab, text="Thư mục kết quả:").grid(row=1, column=0, sticky="w", pady=5)
        self._folder_picker(tab, self.white_output, 1)
        controls = ttk.Frame(tab)
        controls.grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Button(controls, text="Nạp ảnh preview", command=self.load_paint_preview).pack(side="left")
        ttk.Button(controls, text="Chọn màu...", command=self.choose_paint_color).pack(side="left", padx=(8, 4))
        self.color_swatch = tk.Canvas(controls, width=28, height=22, highlightthickness=1, highlightbackground="#777")
        self.color_swatch.pack(side="left", padx=3)
        self.color_swatch.create_rectangle(0, 0, 30, 24, fill="#FFFFFF", outline="")
        ttk.Label(controls, text="Mã màu:").pack(side="left", padx=(8, 3))
        color_entry = ttk.Entry(controls, textvariable=self.paint_color, width=10)
        color_entry.pack(side="left")
        color_entry.bind("<FocusOut>", lambda _event: self.update_paint_color())
        color_entry.bind("<Return>", lambda _event: self.update_paint_color())
        self.eyedropper_button = ttk.Button(controls, text="Bút chấm lấy màu", command=self.toggle_eyedropper)
        self.eyedropper_button.pack(side="left", padx=8)
        ttk.Button(controls, text="Hoàn tác vùng cuối", command=self.undo_paint_region).pack(side="left")
        ttk.Button(controls, text="Xóa tất cả vùng", command=self.clear_paint_regions).pack(side="left", padx=4)
        ttk.Button(controls, text="Vùng dưới 70%", command=self.reset_paint_region).pack(side="left")

        ttk.Label(
            tab,
            text="Mỗi lần kéo sẽ thêm một vùng với màu hiện tại. Có thể đổi màu rồi kéo tiếp để tạo vùng màu khác.",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 5))
        action_row = ttk.Frame(tab)
        action_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(action_row, text="Chế độ:").pack(side="left")
        ttk.Combobox(
            action_row,
            textvariable=self.paint_mode,
            values=("Vùng đánh dấu thủ công", "Theo dòng chữ (Tesseract)"),
            state="readonly",
            width=25,
        ).pack(side="left", padx=(4, 8))
        ttk.Label(action_row, text="Tìm:").pack(side="left")
        ttk.Entry(action_row, textvariable=self.follow_text, width=22).pack(side="left", padx=4)
        ttk.Label(action_row, text="Đệm px:").pack(side="left")
        ttk.Spinbox(action_row, from_=0, to=100, textvariable=self.follow_padding, width=5).pack(side="left", padx=4)
        ttk.Button(action_row, text="Xem vùng tìm được", command=self.preview_follow_text).pack(side="left", padx=5)
        ttk.Checkbutton(action_row, text="Bao gồm thư mục con", variable=self.white_recursive).pack(side="left")
        ttk.Button(action_row, text="Áp dụng vùng và màu cho tất cả ảnh", command=self.run_whiten).pack(side="left", padx=12)

        self.paint_canvas = tk.Canvas(tab, background="#252525", highlightthickness=1, highlightbackground="#666")
        self.paint_canvas.grid(row=5, column=0, columnspan=3, sticky="nsew")
        self.paint_canvas.bind("<Configure>", lambda _event: self.draw_paint_preview())
        self.paint_canvas.bind("<ButtonPress-1>", self.paint_canvas_press)
        self.paint_canvas.bind("<B1-Motion>", self.paint_canvas_drag)
        self.paint_canvas.bind("<ButtonRelease-1>", self.paint_canvas_release)

    def load_paint_preview(self) -> None:
        folder = Path(self.white_input.get())
        if not folder.is_dir():
            messagebox.showerror("Lỗi", "Hãy chọn thư mục nguồn hợp lệ.")
            return
        files = list_images(folder, self.white_recursive.get())
        if not files:
            messagebox.showerror("Lỗi", "Không tìm thấy ảnh trong thư mục nguồn.")
            return
        self.paint_preview_path = files[0]
        with Image.open(files[0]) as image:
            self.paint_preview_image = image.convert("RGB")
        self.draw_paint_preview()
        self.status.set(f"Đang preview: {files[0].name}. Kéo chuột để chọn vùng tô.")

    def draw_paint_preview(self) -> None:
        if self.paint_preview_image is None or not hasattr(self, "paint_canvas"):
            return
        canvas_w = max(1, self.paint_canvas.winfo_width())
        canvas_h = max(1, self.paint_canvas.winfo_height())
        source = self.paint_preview_image
        scale = min(canvas_w / source.width, canvas_h / source.height)
        width = max(1, round(source.width * scale))
        height = max(1, round(source.height * scale))
        left = (canvas_w - width) // 2
        top = (canvas_h - height) // 2
        display = source.resize((width, height), Image.Resampling.LANCZOS)
        self.paint_preview_photo = ImageTk.PhotoImage(display)
        self.paint_display_box = (left, top, width, height)
        self.paint_canvas.delete("all")
        self.paint_canvas.create_image(left, top, image=self.paint_preview_photo, anchor="nw", tags="preview")
        self.draw_paint_selection()

    def draw_paint_selection(self) -> None:
        self.paint_canvas.delete("selection")
        left, top, width, height = self.paint_display_box
        regions = list(self.paint_regions)
        if self.paint_region is not None:
            regions.append((*self.paint_region, self.valid_paint_color(show_error=False) or "#FFFFFF"))
        for index, (x1, y1, x2, y2, color) in enumerate(regions, 1):
            self.paint_canvas.create_rectangle(
                left + x1 * width,
                top + y1 * height,
                left + x2 * width,
                top + y2 * height,
                outline="#FF3030",
                width=3,
                fill=color,
                stipple="gray25",
                tags="selection",
            )
            self.paint_canvas.create_text(
                left + x1 * width + 7,
                top + y1 * height + 7,
                text=str(index),
                fill="#FF3030",
                anchor="nw",
                font=("Segoe UI", 12, "bold"),
                tags="selection",
            )

    def canvas_to_normalized(self, x: int, y: int) -> tuple[float, float]:
        left, top, width, height = self.paint_display_box
        nx = max(0.0, min(1.0, (x - left) / width))
        ny = max(0.0, min(1.0, (y - top) / height))
        return nx, ny

    def point_inside_preview(self, x: int, y: int) -> bool:
        left, top, width, height = self.paint_display_box
        return left <= x <= left + width and top <= y <= top + height

    def paint_canvas_press(self, event: tk.Event) -> None:
        if self.paint_preview_image is None or not self.point_inside_preview(event.x, event.y):
            return
        if self.paint_eyedropper:
            nx, ny = self.canvas_to_normalized(event.x, event.y)
            px = min(self.paint_preview_image.width - 1, round(nx * (self.paint_preview_image.width - 1)))
            py = min(self.paint_preview_image.height - 1, round(ny * (self.paint_preview_image.height - 1)))
            red, green, blue = self.paint_preview_image.getpixel((px, py))
            self.paint_color.set(f"#{red:02X}{green:02X}{blue:02X}")
            self.update_paint_color()
            self.paint_eyedropper = False
            self.eyedropper_button.configure(text="Bút chấm lấy màu")
            self.status.set(f"Đã lấy màu {self.paint_color.get()} tại điểm vừa chọn.")
            return
        if self.paint_default_region:
            self.paint_regions.clear()
            self.paint_default_region = False
        self.paint_drag_start = (event.x, event.y)
        nx, ny = self.canvas_to_normalized(event.x, event.y)
        self.paint_region = (nx, ny, nx, ny)

    def paint_canvas_drag(self, event: tk.Event) -> None:
        if self.paint_drag_start is None:
            return
        start_x, start_y = self.paint_drag_start
        x1, y1 = self.canvas_to_normalized(start_x, start_y)
        x2, y2 = self.canvas_to_normalized(event.x, event.y)
        self.paint_region = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        self.draw_paint_selection()

    def paint_canvas_release(self, event: tk.Event) -> None:
        if self.paint_drag_start is None:
            return
        self.paint_canvas_drag(event)
        self.paint_drag_start = None
        if self.paint_region is None:
            return
        x1, y1, x2, y2 = self.paint_region
        if x2 - x1 >= 0.001 and y2 - y1 >= 0.001:
            color = self.valid_paint_color(show_error=False) or "#FFFFFF"
            self.paint_regions.append((x1, y1, x2, y2, color))
        self.paint_region = None
        self.draw_paint_selection()
        self.status.set(f"Đã tạo {len(self.paint_regions)} vùng tô.")

    def valid_paint_color(self, show_error: bool = True) -> str | None:
        value = self.paint_color.get().strip()
        if value and not value.startswith("#"):
            value = f"#{value}"
        try:
            ImageColor.getrgb(value)
        except ValueError:
            if show_error:
                messagebox.showerror("Màu không hợp lệ", "Nhập mã màu dạng #RRGGBB, ví dụ #FFFFFF.")
            return None
        return value.upper()

    def update_paint_color(self) -> None:
        color = self.valid_paint_color()
        if color is None:
            return
        self.paint_color.set(color)
        self.color_swatch.itemconfigure("all", fill=color)
        self.draw_paint_selection()

    def choose_paint_color(self) -> None:
        selected = colorchooser.askcolor(color=self.paint_color.get(), title="Chọn màu tô")
        if selected[1]:
            self.paint_color.set(selected[1].upper())
            self.update_paint_color()

    def toggle_eyedropper(self) -> None:
        if self.paint_preview_image is None:
            self.load_paint_preview()
            if self.paint_preview_image is None:
                return
        self.paint_eyedropper = not self.paint_eyedropper
        text = "Đang lấy màu — nhấp lên ảnh" if self.paint_eyedropper else "Bút chấm lấy màu"
        self.eyedropper_button.configure(text=text)

    def reset_paint_region(self) -> None:
        color = self.valid_paint_color(show_error=False) or "#FFFFFF"
        self.paint_regions = [(0.0, 0.70, 1.0, 1.0, color)]
        self.paint_region = None
        self.paint_default_region = True
        self.draw_paint_selection()

    def undo_paint_region(self) -> None:
        if self.paint_regions:
            self.paint_regions.pop()
        self.paint_default_region = False
        self.draw_paint_selection()
        self.status.set(f"Còn {len(self.paint_regions)} vùng tô.")

    def clear_paint_regions(self) -> None:
        self.paint_regions.clear()
        self.paint_region = None
        self.paint_default_region = False
        self.draw_paint_selection()
        self.status.set("Đã xóa tất cả vùng tô. Kéo trên ảnh để tạo vùng mới.")

    def preview_follow_text(self) -> None:
        self.paint_mode.set("Theo dòng chữ (Tesseract)")
        if self.paint_preview_path is None:
            self.load_paint_preview()
        if self.paint_preview_path is None or self.paint_preview_image is None:
            return
        try:
            boxes = locate_text_lines_with_tesseract(self.paint_preview_path, self.follow_text.get())
        except Exception as exc:
            messagebox.showerror("Không thể tìm chữ", str(exc))
            return
        if not boxes:
            messagebox.showwarning("Không tìm thấy", f"Không tìm thấy dòng chứa: {self.follow_text.get()}")
            return
        padding = max(0, self.follow_padding.get())
        self.paint_regions = []
        for left, top, right, bottom, _text in boxes:
            self.paint_regions.append((
                max(0, left - padding) / self.paint_preview_image.width,
                max(0, top - padding) / self.paint_preview_image.height,
                min(self.paint_preview_image.width, right + padding) / self.paint_preview_image.width,
                min(self.paint_preview_image.height, bottom + padding) / self.paint_preview_image.height,
                self.valid_paint_color(show_error=False) or "#FFFFFF",
            ))
        self.paint_default_region = False
        self.paint_region = None
        self.draw_paint_selection()
        self.status.set(f"Tesseract tìm thấy {len(boxes)} dòng trên ảnh preview.")

    def run_whiten(self) -> None:
        source = Path(self.white_input.get())
        if not source.is_dir():
            messagebox.showerror("Lỗi", "Thư mục nguồn không hợp lệ.")
            return
        output = Path(self.white_output.get()) if self.white_output.get() else source.with_name(f"{source.name}_white")
        if output.resolve() == source.resolve():
            messagebox.showerror("Lỗi", "Hãy chọn thư mục kết quả khác thư mục nguồn.")
            return
        files = list_images(source, self.white_recursive.get())
        follow_mode = self.paint_mode.get().startswith("Theo dòng chữ")
        if not follow_mode and not self.paint_regions:
            messagebox.showerror("Lỗi", "Chưa có vùng tô. Hãy kéo chọn ít nhất một vùng trên ảnh preview.")
            return
        color = self.valid_paint_color()
        if color is None:
            return
        missing: list[str] = []
        matched_lines = 0
        try:
            for path in files:
                relative = path.relative_to(source)
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(path) as image:
                    image = image.convert("RGB")
                    draw = ImageDraw.Draw(image)
                    if follow_mode:
                        boxes = locate_text_lines_with_tesseract(path, self.follow_text.get())
                        if not boxes:
                            missing.append(path.name)
                            continue
                        padding = max(0, self.follow_padding.get())
                        for left, top, right, bottom, _text in boxes:
                            box = (
                                max(0, left - padding), max(0, top - padding),
                                min(image.width, right + padding), min(image.height, bottom + padding),
                            )
                            draw.rectangle(box, fill=ImageColor.getrgb(color))
                            matched_lines += 1
                    else:
                        for x1, y1, x2, y2, region_color in self.paint_regions:
                            box = (
                                round(x1 * image.width), round(y1 * image.height),
                                round(x2 * image.width), round(y2 * image.height),
                            )
                            draw.rectangle(box, fill=ImageColor.getrgb(region_color))
                    kwargs = {"quality": 95} if target.suffix.lower() in {".jpg", ".jpeg", ".webp"} else {}
                    image.save(target, **kwargs)
        except Exception as exc:
            messagebox.showerror("Thất bại", str(exc))
            return
        if follow_mode:
            detail = f"Đã tô {matched_lines} dòng trên {len(files) - len(missing)}/{len(files)} ảnh vào:\n{output}"
            if missing:
                detail += f"\n\nKhông tìm thấy chữ trong {len(missing)} ảnh:\n" + "\n".join(missing[:10])
                if len(missing) > 10:
                    detail += f"\n... và {len(missing) - 10} ảnh khác"
            messagebox.showinfo("Hoàn tất", detail)
        else:
            messagebox.showinfo("Hoàn tất", f"Đã tô {len(self.paint_regions)} vùng trên {len(files)} ảnh vào:\n{output}")

    def _build_shift_tab(self) -> None:
        tab = self.shift_tab
        tab.columnconfigure(1, weight=1)
        self.shift_folder = tk.StringVar()
        self.shift_prefix = tk.StringVar(value="HCM202 SU26 FE_")
        self.shift_ext = tk.StringVar(value=".jpg")
        self.shift_start = tk.IntVar(value=21)
        self.shift_minus = tk.IntVar(value=1)
        self.shift_digits = tk.IntVar(value=3)
        ttk.Label(tab, text="Thư mục:").grid(row=0, column=0, sticky="w", pady=5)
        self._folder_picker(tab, self.shift_folder, 0)
        fields = (
            ("Prefix:", self.shift_prefix), ("Đuôi file:", self.shift_ext),
            ("Bắt đầu từ số:", self.shift_start), ("Trừ đi:", self.shift_minus),
            ("Số chữ số:", self.shift_digits),
        )
        for row, (label, variable) in enumerate(fields, 1):
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Entry(tab, textvariable=variable, width=30).grid(row=row, column=1, sticky="w", padx=6)
        ttk.Button(tab, text="Thực hiện dịch số", command=self.run_shift).grid(row=6, column=1, sticky="w", padx=6, pady=14)

    def run_shift(self) -> None:
        from shift_image_numbers_down import collect_renames

        folder = Path(self.shift_folder.get())
        if not folder.is_dir():
            messagebox.showerror("Lỗi", "Thư mục không hợp lệ.")
            return
        pairs = collect_renames(folder, self.shift_prefix.get(), self.shift_ext.get(), self.shift_start.get(), self.shift_minus.get(), self.shift_digits.get())
        items = [RenameItem(source, target, index) for index, (source, target) in enumerate(pairs)]
        if not items:
            messagebox.showinfo("Thông báo", "Không có file phù hợp.")
            return
        preview = "\n".join(f"{i.source.name} → {i.target.name}" for i in items[:12])
        if len(items) > 12:
            preview += f"\n... và {len(items) - 12} file khác"
        if not messagebox.askyesno("Xác nhận", f"{preview}\n\nTiếp tục?"):
            return
        try:
            count, backup, collision_count = execute_safe_rename(items)
        except Exception as exc:
            messagebox.showerror("Thất bại", str(exc))
            return
        text = f"Đã đổi tên {count} file."
        if backup:
            text += f"\nĐã backup {collision_count} file trùng vào {backup}"
        messagebox.showinfo("Hoàn tất", text)

    def _build_prefix_tab(self) -> None:
        tab = self.prefix_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(3, weight=1)
        self.prefix_folder = tk.StringVar()
        self.new_prefix = tk.StringVar()
        ttk.Label(tab, text="Thư mục ảnh:").grid(row=0, column=0, sticky="w", pady=5)
        self._folder_picker(tab, self.prefix_folder, 0)
        ttk.Label(tab, text="Prefix mới (không cần dấu _ cuối):").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(tab, textvariable=self.new_prefix).grid(row=1, column=1, sticky="ew", padx=6)
        actions = ttk.Frame(tab)
        actions.grid(row=2, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Button(actions, text="Xem trước", command=self.preview_prefix_rename).pack(side="left")
        ttk.Button(actions, text="Thực hiện đổi prefix", command=self.apply_prefix_rename).pack(side="left", padx=6)
        self.prefix_tree = ttk.Treeview(tab, columns=("old", "new", "state"), show="headings")
        for key, title, width in (
            ("old", "Tên hiện tại", 360),
            ("new", "Tên mới", 360),
            ("state", "Trạng thái", 260),
        ):
            self.prefix_tree.heading(key, text=title)
            self.prefix_tree.column(key, width=width, anchor="w")
        self.prefix_tree.grid(row=3, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.prefix_tree.yview)
        scrollbar.grid(row=3, column=3, sticky="ns")
        self.prefix_tree.configure(yscrollcommand=scrollbar.set)

    def _prefix_rename_items(self) -> list[RenameItem]:
        folder = Path(self.prefix_folder.get())
        if not folder.is_dir():
            raise ValueError("Hãy chọn thư mục ảnh hợp lệ.")
        prefix = self.new_prefix.get().strip().rstrip("_")
        if not prefix:
            raise ValueError("Prefix mới không được để trống.")
        items: list[RenameItem] = []
        for index, source in enumerate(list_images(folder)):
            last_part = source.stem.rsplit("_", 1)[-1]
            target = source.with_name(f"{prefix}_{last_part}{source.suffix}")
            items.append(RenameItem(source, target, index))
        validate_rename_items(items)
        return items

    def preview_prefix_rename(self) -> list[RenameItem] | None:
        self.prefix_tree.delete(*self.prefix_tree.get_children())
        try:
            items = self._prefix_rename_items()
        except ValueError as exc:
            messagebox.showerror("Không thể lập kế hoạch", str(exc))
            return None
        sources = {item.source.resolve() for item in items}
        for item in items:
            if item.source.resolve() == item.target.resolve():
                state = "Tên đã đúng"
            elif item.target.exists() and item.target.resolve() not in sources:
                state = "Trùng file cũ → sẽ backup"
            else:
                state = "Sẵn sàng"
            self.prefix_tree.insert("", "end", values=(item.source.name, item.target.name, state))
        self.status.set(f"Đã xem trước đổi prefix cho {len(items)} ảnh.")
        return items

    def apply_prefix_rename(self) -> None:
        items = self.preview_prefix_rename()
        if not items:
            return
        changed = sum(item.source.resolve() != item.target.resolve() for item in items)
        if not changed:
            messagebox.showinfo("Thông báo", "Tất cả file đã có đúng prefix.")
            return
        if not messagebox.askyesno("Xác nhận", f"Đổi prefix cho {changed} file theo bảng xem trước?"):
            return
        try:
            count, backup, collision_count = execute_safe_rename(items)
        except Exception as exc:
            messagebox.showerror("Đổi prefix thất bại", str(exc))
            return
        text = f"Đã đổi prefix cho {count} file."
        if backup:
            text += f"\nĐã backup {collision_count} file trùng vào:\n{backup}"
        messagebox.showinfo("Hoàn tất", text)
        self.preview_prefix_rename()

    def _build_crop_tab(self) -> None:
        tab = self.crop_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(3, weight=1)
        self.crop_input = tk.StringVar()
        self.crop_output = tk.StringVar()
        self.crop_image: Image.Image | None = None
        self.crop_photo: ImageTk.PhotoImage | None = None
        self.crop_lines: list[float] = []
        self.crop_preview_scale = 1.0
        self.crop_zoom = 1.0
        self.crop_drag_line: int | None = None

        ttk.Label(tab, text="Ảnh dài:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.crop_input).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(tab, text="Chọn ảnh", command=self.choose_crop_image).grid(row=0, column=2)
        ttk.Label(tab, text="Thư mục kết quả:").grid(row=1, column=0, sticky="w", pady=4)
        self._folder_picker(tab, self.crop_output, 1)

        actions = ttk.Frame(tab)
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Button(actions, text="Hoàn tác đường cuối", command=self.undo_crop_line).pack(side="left")
        ttk.Button(actions, text="Xóa tất cả đường", command=self.clear_crop_lines).pack(side="left", padx=6)
        ttk.Button(actions, text="Xuất các ảnh đã cắt", command=self.export_crops).pack(side="left")
        ttk.Separator(actions, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(actions, text="−", width=3, command=lambda: self.change_crop_zoom(0.8)).pack(side="left")
        self.crop_zoom_text = tk.StringVar(value="100%")
        ttk.Label(actions, textvariable=self.crop_zoom_text, width=7, anchor="center").pack(side="left")
        ttk.Button(actions, text="+", width=3, command=lambda: self.change_crop_zoom(1.25)).pack(side="left")
        ttk.Button(actions, text="Vừa chiều rộng", command=self.reset_crop_zoom).pack(side="left", padx=(5, 0))
        self.crop_info = tk.StringVar(value="Chọn ảnh, sau đó nhấp lên preview để đặt các đường cắt ngang.")
        ttk.Label(actions, textvariable=self.crop_info).pack(side="left", padx=14)

        preview_frame = ttk.Frame(tab)
        preview_frame.grid(row=3, column=0, columnspan=3, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.crop_canvas = tk.Canvas(preview_frame, background="#282828", highlightthickness=1, highlightbackground="#666")
        self.crop_canvas.grid(row=0, column=0, sticky="nsew")
        crop_scroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.crop_canvas.yview)
        crop_scroll.grid(row=0, column=1, sticky="ns")
        self.crop_canvas.configure(yscrollcommand=crop_scroll.set)
        self.crop_canvas.bind("<ButtonPress-1>", self.crop_line_press)
        self.crop_canvas.bind("<B1-Motion>", self.crop_line_drag)
        self.crop_canvas.bind("<ButtonRelease-1>", self.crop_line_release)
        self.crop_canvas.bind("<Button-3>", self.remove_nearest_crop_line)
        self.crop_canvas.bind("<MouseWheel>", self.scroll_crop_canvas)

    def choose_crop_image(self) -> None:
        initial = str(Path(self.crop_input.get()).parent) if self.crop_input.get() else None
        selected = filedialog.askopenfilename(
            initialdir=initial,
            title="Chọn ảnh dài cần cắt",
            filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"), ("Tất cả file", "*.*")],
        )
        if not selected:
            return
        path = Path(selected)
        self.crop_input.set(str(path))
        if not self.crop_output.get():
            self.crop_output.set(str(path.parent / f"{path.stem}_cut"))
        try:
            with Image.open(path) as image:
                self.crop_image = image.convert("RGB")
        except Exception as exc:
            messagebox.showerror("Không mở được ảnh", str(exc))
            return
        self.crop_lines.clear()
        self.crop_zoom = 1.0
        self.crop_zoom_text.set("100%")
        self.draw_crop_preview()
        self.status.set(f"Đã nạp {path.name}: {self.crop_image.width} × {self.crop_image.height} px.")

    def draw_crop_preview(self) -> None:
        if self.crop_image is None:
            return
        self.crop_canvas.update_idletasks()
        old_preview_height = self.crop_image.height * self.crop_preview_scale
        old_top_ratio = self.crop_canvas.canvasy(0) / old_preview_height if old_preview_height > 1 else 0.0
        available_width = max(300, self.crop_canvas.winfo_width() - 30)
        preview_width = min(1600, max(150, round(available_width * self.crop_zoom)))
        self.crop_preview_scale = preview_width / self.crop_image.width
        preview_height = max(1, round(self.crop_image.height * self.crop_preview_scale))
        preview = self.crop_image.resize((preview_width, preview_height), Image.Resampling.LANCZOS)
        self.crop_photo = ImageTk.PhotoImage(preview)
        self.crop_canvas.delete("all")
        self.crop_canvas.create_image(0, 0, image=self.crop_photo, anchor="nw", tags="crop_image")
        self.crop_canvas.configure(scrollregion=(0, 0, preview_width, preview_height))
        self.crop_canvas.yview_moveto(max(0.0, min(1.0, old_top_ratio)))
        self.draw_crop_lines()

    def draw_crop_lines(self) -> None:
        self.crop_canvas.delete("crop_line")
        if self.crop_image is None:
            return
        width = round(self.crop_image.width * self.crop_preview_scale)
        for index, ratio in enumerate(sorted(self.crop_lines), 1):
            y = ratio * self.crop_image.height * self.crop_preview_scale
            self.crop_canvas.create_line(0, y, width, y, fill="#FF2020", width=3, tags="crop_line")
            self.crop_canvas.create_text(8, y - 5, text=f"Cắt {index}", fill="#FF2020", anchor="sw", font=("Segoe UI", 11, "bold"), tags="crop_line")
        self.crop_info.set(f"{len(self.crop_lines)} đường cắt → {len(self.crop_lines) + 1} ảnh kết quả")

    def crop_event_ratio(self, event: tk.Event) -> float:
        if self.crop_image is None:
            return 0.0
        preview_height = self.crop_image.height * self.crop_preview_scale
        return max(0.0, min(1.0, self.crop_canvas.canvasy(event.y) / preview_height))

    def crop_line_press(self, event: tk.Event) -> None:
        if self.crop_image is None:
            return
        ratio = self.crop_event_ratio(event)
        if self.crop_lines:
            nearest_index = min(range(len(self.crop_lines)), key=lambda index: abs(self.crop_lines[index] - ratio))
            distance = abs(self.crop_lines[nearest_index] - ratio) * self.crop_image.height * self.crop_preview_scale
            if distance <= 12:
                self.crop_drag_line = nearest_index
                self.crop_canvas.configure(cursor="sb_v_double_arrow")
                return
        if not 0.002 < ratio < 0.998:
            return
        min_gap = 3 / self.crop_image.height
        if any(abs(existing - ratio) < min_gap for existing in self.crop_lines):
            return
        self.crop_lines.append(ratio)
        self.draw_crop_lines()
        self.status.set(f"Đã thêm đường cắt tại Y = {round(ratio * self.crop_image.height)} px của ảnh gốc.")

    def crop_line_drag(self, event: tk.Event) -> None:
        if self.crop_drag_line is None or self.crop_image is None:
            return
        ratio = max(0.002, min(0.998, self.crop_event_ratio(event)))
        self.crop_lines[self.crop_drag_line] = ratio
        self.draw_crop_lines()
        self.status.set(f"Đang di chuyển đường cắt: Y = {round(ratio * self.crop_image.height)} px.")

    def crop_line_release(self, _event: tk.Event) -> None:
        if self.crop_drag_line is not None:
            self.crop_drag_line = None
            self.crop_canvas.configure(cursor="")
            self.status.set("Đã cập nhật vị trí đường cắt.")

    def remove_nearest_crop_line(self, event: tk.Event) -> None:
        if not self.crop_lines or self.crop_image is None:
            return
        ratio = self.crop_canvas.canvasy(event.y) / (self.crop_image.height * self.crop_preview_scale)
        nearest = min(self.crop_lines, key=lambda value: abs(value - ratio))
        if abs(nearest - ratio) * self.crop_image.height * self.crop_preview_scale <= 15:
            self.crop_lines.remove(nearest)
            self.draw_crop_lines()

    def undo_crop_line(self) -> None:
        if self.crop_lines:
            self.crop_lines.pop()
            self.draw_crop_lines()

    def clear_crop_lines(self) -> None:
        self.crop_lines.clear()
        self.draw_crop_lines()

    def scroll_crop_canvas(self, event: tk.Event) -> None:
        if event.state & 0x0004:
            self.change_crop_zoom(1.15 if event.delta > 0 else 1 / 1.15)
        else:
            self.crop_canvas.yview_scroll(int(-event.delta / 120), "units")

    def change_crop_zoom(self, factor: float) -> None:
        if self.crop_image is None:
            return
        self.crop_zoom = max(0.25, min(2.0, self.crop_zoom * factor))
        self.crop_zoom_text.set(f"{round(self.crop_zoom * 100)}%")
        self.draw_crop_preview()

    def reset_crop_zoom(self) -> None:
        self.crop_zoom = 1.0
        self.crop_zoom_text.set("100%")
        self.draw_crop_preview()

    def export_crops(self) -> None:
        source = Path(self.crop_input.get())
        if self.crop_image is None or not source.is_file():
            messagebox.showerror("Lỗi", "Hãy chọn và nạp ảnh cần cắt.")
            return
        if not self.crop_lines:
            messagebox.showerror("Lỗi", "Chưa có đường cắt. Hãy nhấp lên preview để đánh dấu.")
            return
        output = Path(self.crop_output.get()) if self.crop_output.get() else source.parent / f"{source.stem}_cut"
        if output.exists() and not output.is_dir():
            messagebox.showerror("Lỗi", "Đường dẫn kết quả đang là một file, không phải thư mục.")
            return
        output.mkdir(parents=True, exist_ok=True)
        boundaries = [0]
        boundaries.extend(sorted({max(1, min(self.crop_image.height - 1, round(r * self.crop_image.height))) for r in self.crop_lines}))
        boundaries.append(self.crop_image.height)
        created: list[Path] = []
        try:
            for index, (top, bottom) in enumerate(zip(boundaries, boundaries[1:]), 1):
                if bottom <= top:
                    continue
                piece = self.crop_image.crop((0, top, self.crop_image.width, bottom))
                target = output / f"{source.stem}_{index:03d}{source.suffix.lower()}"
                kwargs = {"quality": 95} if target.suffix in {".jpg", ".jpeg", ".webp"} else {}
                piece.save(target, **kwargs)
                created.append(target)
        except Exception as exc:
            messagebox.showerror("Cắt ảnh thất bại", str(exc))
            return
        messagebox.showinfo("Hoàn tất", f"Đã xuất {len(created)} ảnh vào:\n{output}")
        self.status.set(f"Đã cắt {source.name} thành {len(created)} ảnh.")


if __name__ == "__main__":
    FUExamApp().mainloop()
