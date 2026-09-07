@echo off
rem Realtime orderbook terminal - live spreads for every market. Press q to quit.
cd /d "%~dp0"
uv run binance-mm live
pause
