import sys
import os
import base64
sys.path.insert(0, "D:/Kestrel")

SETUP_FLAG = "D:/Kestrel/.setup_complete"
ICON_PATH  = "D:/Kestrel/assets/kestrel.ico"
BAT_PATH   = "D:/Kestrel/start_kestrel.bat"

def first_time_setup():
    print("First run detected. Setting up Kestrel...")

    # 1. Run setup.py to create folder structure
    import subprocess
    subprocess.run([sys.executable, "D:/Kestrel/setup.py"])

    # 2. Create .bat file
    bat_content = (
        "@echo off\n"
        "title Kestrel Trading System\n"
        "cd /d D:\\Kestrel\n"
        "D:\\Kestrel\\.venv\\Scripts\\python.exe D:\\Kestrel\\kestrel.py\n"
        "pause\n"
    )
    with open(BAT_PATH, "w") as f:
        f.write(bat_content)
    print(".bat file created.")

    # 3. Create desktop shortcut with icon
    try:
        import winshell
        from win32com.client import Dispatch

        desktop       = winshell.desktop()
        shortcut_path = os.path.join(desktop, "Kestrel.lnk")

        shell    = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath       = BAT_PATH
        shortcut.WorkingDirectory = "D:\\Kestrel"
        shortcut.IconLocation     = ICON_PATH
        shortcut.save()
        print("Desktop shortcut created.")
    except ImportError:
        print("winshell not installed — skipping shortcut creation.")
        print("Run: pip install winshell pywin32")

    # 4. Mark setup complete
    open(SETUP_FLAG, 'w').close()
    print("Setup complete. Starting Kestrel...\n")

if __name__ == "__main__":
    if not os.path.exists(SETUP_FLAG):
        first_time_setup()

    from pipeline.run import run
    run()