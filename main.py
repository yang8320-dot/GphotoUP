import os
import sys
import time
import threading
import win32event, win32api, winerror, win32gui, win32con
import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw

# 導入自定義模組
from gphoto_uploader import GphotoComponent, DBManager
from folder_sync import SyncComponent

WINDOW_TITLE = "GPhotoUP Pro - 全方位雲端管理系統"

# --- 防重複開啟 ---
mutex = win32event.CreateMutex(None, False, "Global\\GPhotoUP_Modular_Instance")
if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
    hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    sys.exit(0)

try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except: pass

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class GPhotoUPPro(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("950x850")
        
        self.db = DBManager()
        self.running = False

        # --- 分頁系統 ---
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        self.tab_gphoto = self.tabview.add("GphotoUp (相簿備份)")
        self.tab_sync = self.tabview.add("Sync (資料同步)")

        self.gphoto_ui = GphotoComponent(self.tab_gphoto, self)
        self.gphoto_ui.pack(fill="both", expand=True)

        self.sync_ui = SyncComponent(self.tab_sync, self)
        self.sync_ui.pack(fill="both", expand=True)

        # 高對比深藍色啟動按鈕
        self.btn_master = ctk.CTkButton(self, text="啟動全方位監控系統", command=self.toggle_all, height=50, font=("Arial", 18, "bold"), fg_color="#1F6AA5", text_color="#FFFFFF")
        self.btn_master.pack(pady=10, padx=40, fill="x")
        
        self.log_area = ctk.CTkTextbox(self, height=150, font=("Consolas", 12))
        self.log_area.pack(pady=10, padx=20, fill="x")
        self.log_area.configure(state="disabled")

        self.protocol('WM_DELETE_WINDOW', self.hide_window)
        self.setup_tray()
        
        # 啟動背景資料庫瘦身
        threading.Thread(target=self.background_cleanup, daemon=True).start()

    def background_cleanup(self):
        self.log("啟動背景資料庫瘦身與檢查，請稍候...")
        self.db.cleanup_ghost_records()
        self.log("資料庫瘦身完成！系統處於最佳狀態。")

    def log(self, msg):
        self.after(0, lambda: (self.log_area.configure(state="normal"), self.log_area.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n"), self.log_area.see("end"), self.log_area.configure(state="disabled")))

    def toggle_all(self):
        if not self.running:
            self.running = True
            self.btn_master.configure(text="🛑 停止系統監控", fg_color="#FF3B30", text_color="#FFFFFF")
            threading.Thread(target=self.main_worker, daemon=True).start()
        else:
            self.running = False
            self.btn_master.configure(text="啟動全方位監控系統", fg_color="#1F6AA5", text_color="#FFFFFF")
            self.log("🛑 任務已暫停")

    def main_worker(self):
        while self.running:
            self.gphoto_ui.run_tasks()
            self.sync_ui.run_tasks()
            for _ in range(60):
                if not self.running: break
                time.sleep(1)

    def setup_tray(self):
        img = Image.new('RGB', (64, 64), (52, 199, 89))
        self.tray = pystray.Icon("GPhotoUP", img, "GPhotoUP Pro", pystray.Menu(pystray.MenuItem('顯示面板', self.show_window), pystray.MenuItem('退出', self.quit_sys)))
        threading.Thread(target=self.tray.run, daemon=True).start()

    def hide_window(self): self.withdraw()
    def show_window(self): self.deiconify(); self.focus_force()
    def quit_sys(self): self.running = False; self.tray.stop(); self.destroy(); sys.exit(0)

if __name__ == "__main__":
    app = GPhotoUPPro()
    app.mainloop()
