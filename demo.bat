@echo off
rem Demo (paper) market maker - no real money. Press Ctrl+C to stop.
cd /d "%~dp0"
uv run binance-mm demo
pause
