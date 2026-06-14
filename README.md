# Tools FUExam

Bộ tool xử lý ảnh hàng loạt cho các file đề thi.

## 1. Tô trắng vùng dưới ảnh

Dùng để che logo/thanh màu ở phía dưới ảnh.

### File cần copy vào folder ảnh

- `tools/whiten_bottom_area.py`
- `tools/run_whiten_bottom_area.bat`

### Cách chạy nhanh

1. Copy 2 file trên vào folder đang chứa ảnh.
2. Double-click `run_whiten_bottom_area.bat`.
3. Ảnh kết quả sẽ nằm trong folder mới có hậu tố `_white`.

Ví dụ folder gốc là:

```text
images
```

Thì folder kết quả sẽ là:

```text
images_white
```

Mặc định tool sẽ tô trắng từ `70%` chiều cao ảnh xuống đến đáy ảnh.

### Chạy bằng lệnh nếu muốn tùy chỉnh

```powershell
python tools\whiten_bottom_area.py "D:\duong-dan\folder-anh" -o "D:\duong-dan\folder-anh-white" --recursive
```

Chỉnh vị trí bắt đầu tô trắng:

```powershell
python tools\whiten_bottom_area.py "D:\duong-dan\folder-anh" -o "D:\duong-dan\folder-anh-white" --top-percent 68 --recursive
```

Sửa đè lên ảnh gốc:

```powershell
python tools\whiten_bottom_area.py "D:\duong-dan\folder-anh" --overwrite
```

Nên chạy ra folder mới trước khi dùng `--overwrite`.

## 2. Đổi số thứ tự file ảnh

Dùng cho trường hợp có các file:

```text
HCM202 SU26 FE_001.jpg
...
HCM202 SU26 FE_061.jpg
```

Và muốn từ file `HCM202 SU26 FE_021.jpg` trở đi bị trừ đi `1` số:

```text
HCM202 SU26 FE_021.jpg -> HCM202 SU26 FE_020.jpg
HCM202 SU26 FE_022.jpg -> HCM202 SU26 FE_021.jpg
...
HCM202 SU26 FE_061.jpg -> HCM202 SU26 FE_060.jpg
```

### File cần copy vào folder ảnh

- `tools/shift_image_numbers_down.py`
- `tools/run_shift_image_numbers_down.bat`

### Cách chạy nhanh

1. Copy 2 file trên vào folder đang chứa ảnh.
2. Double-click `run_shift_image_numbers_down.bat`.

Tool sẽ tự tìm các file đúng format:

```text
HCM202 SU26 FE_###.jpg
```

Mặc định:

- Bắt đầu từ số `021`
- Trừ đi `1`
- Giữ 3 chữ số, ví dụ `021`, `060`

Nếu file đích đã tồn tại, ví dụ `HCM202 SU26 FE_020.jpg`, tool sẽ đưa file cũ vào folder `_rename_backup` trước để tránh mất dữ liệu.

### Chạy thử không đổi file

```powershell
python tools\shift_image_numbers_down.py "D:\duong-dan\folder-anh" --dry-run
```

### Chạy bằng lệnh nếu muốn tùy chỉnh

```powershell
python tools\shift_image_numbers_down.py "D:\duong-dan\folder-anh" --start 21 --minus 1
```

Đổi prefix nếu tên môn/file khác:

```powershell
python tools\shift_image_numbers_down.py "D:\duong-dan\folder-anh" --prefix "HCM202 SU26 FE_" --ext ".jpg"
```

## Yêu cầu

Máy cần có:

- Python
- Thư viện Pillow cho tool tô trắng ảnh

Kiểm tra Pillow:

```powershell
python -c "from PIL import Image; print('Pillow OK')"
```

Nếu chưa có Pillow:

```powershell
pip install pillow
```
