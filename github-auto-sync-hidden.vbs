Set shell = CreateObject("WScript.Shell")
command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\Users\vashu\OneDrive\Documents\Telegram Bot\github-auto-sync.ps1"""
shell.Run command, 0, True
