@echo off
chcp 65001 >nul 2>&1
title DG-LAB Sensora Build

echo ========================================
echo   DG-LAB Sensora - Nuitka Build
echo ========================================
echo.

python -m nuitka --version >nul 2>&1
if errorlevel 1 (
    echo Nuitka not found, installing...
    pip install nuitka ordered-set zstandard
    echo.
)

set "BUILD_DIR=C:\NuitkaBuild\sensora"
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
mkdir "%BUILD_DIR%"

xcopy /s /e /q /y "%~dp0*.*" "%BUILD_DIR%\" >nul 2>&1

echo Building in %BUILD_DIR% ...
echo.

pushd "%BUILD_DIR%"

python -m nuitka --onefile --standalone --windows-console-mode=disable --windows-icon-from-ico=icon.ico --disable-plugin=pywebview --include-data-dir=web=web --include-package=pythonosc --include-package=pydglab_ws --include-package=aiohttp --include-package=yarl --include-package=multidict --include-package=aiosignal --include-package=frozenlist --include-package=qrcode --include-package=webview --include-package=clr_loader --include-package=pythonnet --nofollow-import-to=tkinter --nofollow-import-to=webview.platforms.android --nofollow-import-to=webview.platforms.gtk --nofollow-import-to=webview.platforms.cocoa --output-filename=DG-LAB-Sensora.exe --output-dir=output --assume-yes-for-downloads --remove-output --company-name=PuddingKC --product-name="DG-LAB Sensora" --product-version=2.0.1 --file-description="DG-LAB VRChat Integration Tool" main.py

popd

echo.
if exist "%BUILD_DIR%\output\DG-LAB-Sensora.exe" (
    if not exist "%~dp0dist" mkdir "%~dp0dist"
    copy /y "%BUILD_DIR%\output\DG-LAB-Sensora.exe" "%~dp0dist\DG-LAB-Sensora.exe" >nul
    rmdir /s /q "%BUILD_DIR%"
    echo Build OK!
    echo Output: dist\DG-LAB-Sensora.exe
) else (
    echo Build FAILED
    echo Check: %BUILD_DIR%
)

echo.
pause
