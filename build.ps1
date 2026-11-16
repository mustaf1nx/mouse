$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
py -3 -m venv .venv
if ($LASTEXITCODE) { throw 'venv failed' }
& ./.venv/Scripts/python.exe -m pip install -r requirements-build.lock
if ($LASTEXITCODE) { throw 'Dependency installation failed' }
& ./.venv/Scripts/python.exe -m PyInstaller --noconfirm --onefile --windowed --name MouseAssistant --distpath windows --workpath build/client --specpath build --hidden-import pynput.mouse._win32 --hidden-import pynput.keyboard._win32 src/client_mouse.py
if ($LASTEXITCODE) { throw 'Client build failed' }
& ./.venv/Scripts/python.exe -m PyInstaller --noconfirm --onefile --console --name MouseAssistantServer --distpath windows --workpath build/server --specpath build src/server.py
if ($LASTEXITCODE) { throw 'Server build failed' }

