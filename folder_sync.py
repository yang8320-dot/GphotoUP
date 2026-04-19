import os
import sys
import subprocess
import customtkinter as ctk
from tkinter import filedialog

def get_rclone_path():
    # 資料夾模式下，rclone.exe 會在 .exe 的同一個資料夾
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    return os.path.join(base, 'rclone.exe')

class SyncComponent(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        # 這裡放置原本 SyncTabFrame 的 UI：來源、目標、限速輸入、任務清單
        self.setup_ui()

    def setup_ui(self):
        # 建立 UI 元件邏輯
        pass

    def run_tasks(self):
        tasks = self.app.db.get_sync_tasks()
        for tid, src, tgt, bw in tasks:
            if not self.app.running: break
            self.execute_rclone(src, tgt, bw)

    def execute_rclone(self, src, tgt, bw):
        rclone_exe = get_rclone_path()
        cmd = [rclone_exe, "sync", src, tgt, "--ignore-existing"]
        if bw: cmd.extend(["--bwlimit", bw])
        
        try:
            subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW)
            self.app.log(f"✅ [Sync] {os.path.basename(src)} 同步完成")
        except Exception as e:
            self.app.log(f"❌ Rclone 錯誤: {e}")
