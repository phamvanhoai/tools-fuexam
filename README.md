# Tools FUExam

Bo tool xu ly anh hang loat cho cac file de thi.

## 1. To trang vung duoi anh

Dung de che logo/thanh mau o phia duoi anh.

### File can copy vao folder anh

- `tools/whiten_bottom_area.py`
- `tools/run_whiten_bottom_area.bat`

### Cach chay nhanh

1. Copy 2 file tren vao folder dang chua anh.
2. Double-click `run_whiten_bottom_area.bat`.
3. Anh ket qua se nam trong folder moi co hau to `_white`.

Vi du folder goc la:

```text
images
```

Thi folder ket qua se la:

```text
images_white
```

Mac dinh tool se to trang tu `70%` chieu cao anh xuong den day anh.

### Chay bang lenh neu muon tuy chinh

```powershell
python tools\whiten_bottom_area.py "D:\duong-dan\folder-anh" -o "D:\duong-dan\folder-anh-white" --recursive
```

Chinh vi tri bat dau to trang:

```powershell
python tools\whiten_bottom_area.py "D:\duong-dan\folder-anh" -o "D:\duong-dan\folder-anh-white" --top-percent 68 --recursive
```

Sua de len anh goc:

```powershell
python tools\whiten_bottom_area.py "D:\duong-dan\folder-anh" --overwrite
```

Nen chay ra folder moi truoc khi dung `--overwrite`.

## 2. Doi so thu tu file anh

Dung cho truong hop co cac file:

```text
HCM202 SU26 FE_001.jpg
...
HCM202 SU26 FE_061.jpg
```

Va muon tu file `HCM202 SU26 FE_021.jpg` tro di bi tru di `1` so:

```text
HCM202 SU26 FE_021.jpg -> HCM202 SU26 FE_020.jpg
HCM202 SU26 FE_022.jpg -> HCM202 SU26 FE_021.jpg
...
HCM202 SU26 FE_061.jpg -> HCM202 SU26 FE_060.jpg
```

### File can copy vao folder anh

- `tools/shift_image_numbers_down.py`
- `tools/run_shift_image_numbers_down.bat`

### Cach chay nhanh

1. Copy 2 file tren vao folder dang chua anh.
2. Double-click `run_shift_image_numbers_down.bat`.

Tool se tu tim cac file dung format:

```text
HCM202 SU26 FE_###.jpg
```

Mac dinh:

- Bat dau tu so `021`
- Tru di `1`
- Giu 3 chu so, vi du `021`, `060`

Neu file dich da ton tai, vi du `HCM202 SU26 FE_020.jpg`, tool se dua file cu vao folder `_rename_backup` truoc de tranh mat du lieu.

### Chay thu khong doi file

```powershell
python tools\shift_image_numbers_down.py "D:\duong-dan\folder-anh" --dry-run
```

### Chay bang lenh neu muon tuy chinh

```powershell
python tools\shift_image_numbers_down.py "D:\duong-dan\folder-anh" --start 21 --minus 1
```

Doi prefix neu ten mon/file khac:

```powershell
python tools\shift_image_numbers_down.py "D:\duong-dan\folder-anh" --prefix "HCM202 SU26 FE_" --ext ".jpg"
```

## Yeu cau

May can co:

- Python
- Thu vien Pillow cho tool to trang anh

Kiem tra Pillow:

```powershell
python -c "from PIL import Image; print('Pillow OK')"
```

Neu chua co Pillow:

```powershell
pip install pillow
```
