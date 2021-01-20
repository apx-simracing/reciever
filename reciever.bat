@echo off
python.exe --version

set needle = Lib

if not exist "Lib" (
  REM Download pip
  powershell -Command "Invoke-WebRequest https://bootstrap.pypa.io/get-pip.py -OutFile get-pip.py"
  REM install pip
  python.exe get-pip.py
  REM insta install dependencies
  python.exe -m pip install -r requirements.txt
  
  python.exe reciever.py
) else (
  python.exe reciever.py
)
