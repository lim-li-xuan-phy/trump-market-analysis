@echo off
echo Compiling event_study_engine.cpp...
g++ -O3 -std=c++17 event_study_engine.cpp -o event_study_engine.exe -lstdc++fs
if %ERRORLEVEL% NEQ 0 (
    echo Compilation of event_study_engine failed!
    exit /b %ERRORLEVEL%
)

echo Compiling backtester.cpp...
g++ -O3 -std=c++17 backtester.cpp -o backtester.exe -lstdc++fs
if %ERRORLEVEL% NEQ 0 (
    echo Compilation of backtester failed!
    exit /b %ERRORLEVEL%
)

echo Compilation successful! Executables created in src/cpp/

