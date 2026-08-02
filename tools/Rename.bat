@echo off
setlocal EnableDelayedExpansion

set /p "prefix=Nhap prefix (khong can dau _ cuoi): "

for %%f in (*.jpg *.jpeg *.png *.webp *.gif *.bmp) do (
    set "name=%%~nf"
    set "ext=%%~xf"

    for %%a in ("!name:_=" "!") do set "last=%%~a"

    set "newname=%prefix%_!last!!ext!"
    ren "%%f" "!newname!"
    echo %%f ^> !newname!
)

echo Hoan thanh!
pause