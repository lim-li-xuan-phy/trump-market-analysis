#!/bin/bash
# Exit immediately if a command exits with a non-zero status
set -e

echo "Compiling event_study_engine.cpp..."
g++ -O3 -std=c++17 event_study_engine.cpp -o event_study_engine -lstdc++fs -lpq

echo "Compiling backtester.cpp..."
g++ -O3 -std=c++17 backtester.cpp -o backtester -lstdc++fs -lpq

echo "Compilation successful! Executables created in src/cpp/"
