@echo off
cd /d "C:\Riot Commander"
C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe fix_meta.py >> logs\fix_apply.log 2>&1
C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe main.py