import os
import platform
import shutil
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def check_python():
    print(f"[OK] Python: {sys.version.split()[0]}")

def check_os():
    print(f"[OK] OS: {platform.system()} {platform.release()}")

def check_folders():
    required = ["docs", "core", "workspace", "archive"]
    for folder in required:
        path = os.path.join(PROJECT_DIR, folder)
        if os.path.isdir(path):
            print(f"[OK] {folder}")
        else:
            print(f"[FAIL] {folder} отсутствует")

def check_disk():
    total, used, free = shutil.disk_usage(PROJECT_DIR)
    print(f"[OK] Свободно: {free // (1024**3)} GB")

def main():
    print("=== AION Diagnostics ===")
    check_python()
    check_os()
    check_folders()
    check_disk()
    print("========================")

if __name__ == "__main__":
    main()
