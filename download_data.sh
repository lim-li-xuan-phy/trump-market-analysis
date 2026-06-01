#!/bin/bash
set -e

echo "=================================================="
echo "Starting Data Collection"
echo "=================================================="

# Scrape Trump's social media posts
echo ""
echo "Scraping posts from web (running scrape_posts.py)..."
python scrape_posts.py "$@"

# Download market data
echo ""
echo "Downloading market data (running download_market_data.py)..."
python download_market_data.py "$@"

echo ""
echo "=================================================="
echo "Data collection completed"
echo "=================================================="
