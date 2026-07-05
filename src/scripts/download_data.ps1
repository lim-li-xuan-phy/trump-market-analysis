# Prevent script from continuing if a command fails
$ErrorActionPreference = "Stop"

Write-Host "=================================================="
Write-Host "Starting Data Collection"
Write-Host "=================================================="

# Scrape Trump's social media posts
Write-Host ""
Write-Host "Scraping posts from web (running scrape_posts.py)..."
python scrape_posts.py $args

# Download market data
Write-Host ""
Write-Host "Downloading market data (running download_market_data.py)..."
python download_market_data.py $args

Write-Host ""
Write-Host "=================================================="
Write-Host "Data collection completed"
Write-Host "=================================================="
