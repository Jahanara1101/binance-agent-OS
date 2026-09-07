@echo off
rem Signal the running bot to safe-exit. No window stays open.
start /b "" binance-mm safe-exit >nul 2>&1
