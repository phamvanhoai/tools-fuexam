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

## 3. Ứng dụng giao diện tổng hợp

Chạy file:

```text
tools/run_fuexam_gui.bat
```

Ứng dụng gồm ba chức năng:

- Nhận diện số câu trong ảnh bằng AI local và đổi tên file theo số câu.
- Chọn vùng trực tiếp trên ảnh preview và tô bằng màu tùy chọn.
- Dịch số thứ tự của một nhóm file ảnh.
- Đổi prefix hàng loạt, giữ lại phần cuối sau dấu `_` và đuôi file.

Chế độ nhận diện mặc định là **Tesseract OCR**, nhẹ và nhanh hơn AI vision local. Trên Windows có thể cài bằng:

```powershell
winget install --id UB-Mannheim.TesseractOCR --exact
```

Sau khi cài, đóng và mở lại ứng dụng. Ollama Vision AI vẫn có thể chọn làm phương án dự phòng.

### AI local cho chức năng đổi tên theo số câu

Ứng dụng kết nối với [Ollama](https://ollama.com/) tại máy local. Cài Ollama và tải một model vision, ví dụ:

```powershell
ollama pull qwen2.5vl:3b
```

Model mặc định trong UI là `qwen2.5vl:3b`. Có thể thay bằng model vision khác đã cài trong Ollama.

Quy trình sử dụng an toàn:

1. Chọn thư mục và bấm **Nạp ảnh**.
2. Bấm **AI nhận diện tất cả**.
3. Kiểm tra cột số câu; nhấp đúp một dòng để sửa thủ công nếu AI đọc sai.
4. Bấm **Xem trước tên mới** rồi mới bấm **Thực hiện đổi tên**.

Tùy chọn **Tự giải phóng model khỏi RAM/VRAM sau khi nhận diện** được bật mặc định. Khi hoàn tất, ứng dụng gửi `keep_alive: 0` cho Ollama để giải phóng model ngay; server Ollama vẫn chạy nền và không chiếm bộ nhớ của model.

### Chọn vùng và màu tô trên ảnh

Trong tab **Tô màu vùng ảnh**, nạp ảnh preview rồi kéo chuột để chọn vùng chữ nhật. Mỗi lần kéo sẽ thêm một vùng mới và ghi nhớ màu hiện tại, vì vậy một ảnh có thể có nhiều vùng với nhiều màu khác nhau. Có nút hoàn tác vùng cuối và xóa tất cả vùng. Màu tô có thể được chọn bằng bảng màu, nhập mã HEX như `#FFFFFF`, hoặc dùng **Bút chấm lấy màu** và nhấp trực tiếp lên ảnh. Các vùng được lưu theo tỷ lệ nên có thể áp dụng cho nhiều ảnh có kích thước khác nhau.

Nếu tên mới trùng với một file không thuộc nhóm đang đổi, file cũ sẽ được chuyển vào thư mục `_rename_backup` trước. Việc đổi tên được thực hiện qua tên tạm nên các trường hợp hoán đổi hoặc xoay vòng tên không ghi đè mất ảnh.
