@echo off
echo Compiling event_study_engine.cpp...
g++ -O3 -std=c++17 event_study_engine.cpp -o event_study_engine.exe -lstdc++fs
if %ERRORLEVEL% NEQ 0 (
    echo Compilation failed!
    exit /b %ERRORLEVEL%
)
echo Compilation successful! event_study_engine.exe created in src/cpp/
