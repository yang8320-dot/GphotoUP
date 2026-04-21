# --- START OF FILE main.py ---
import os
import sys
import time
import threading
import winreg  # 🚀 新增：用來操作 Windows 登錄檔 (開機啟動)
import win32event, win32api, winerror, win32gui, win32con
import customtkinter as ctk
import pystray
from PIL import Image

from gphoto_uploader import GphotoComponent, DBManager
from folder_sync import SyncComponent

WINDOW_TITLE = "GPhotoUP Pro - 全方位雲端管理系統"
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME_REG = "GPhotoUP_Pro_System"

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
        self.geometry("550x700") 
        
        self.db = DBManager()
        self.running = False

        self.tabview = ctk.CTkTabview(self, text_color=("#111111", "#EEEEEE"))
        self.tabview._segmented_button.configure(font=("微軟正黑體", 14, "bold"))
        self.tabview.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.tab_gphoto = self.tabview.add("GphotoUp (相簿備份)")
        self.tab_sync = self.tabview.add("Sync (資料同步)")

        self.gphoto_ui = GphotoComponent(self.tab_gphoto, self)
        self.gphoto_ui.pack(fill="both", expand=True)

        self.sync_ui = SyncComponent(self.tab_sync, self)
        self.sync_ui.pack(fill="both", expand=True)

        self.btn_master = ctk.CTkButton(self, text="啟動全方位監控系統", command=self.toggle_all, 
                                       height=50, font=("微軟正黑體", 18, "bold"), 
                                       corner_radius=10, border_width=2,
                                       border_color=("#154c79", "#1F6AA5"),
                                       fg_color="#1F6AA5", text_color="#FFFFFF")
        self.btn_master.pack(pady=10, padx=20, fill="x")
        
        self.log_area = ctk.CTkTextbox(self, height=100, font=("Consolas", 12),
                                       fg_color=("#FFFFFF", "#1E1E1E"), text_color=("#111111", "#EEEEEE"),
                                       border_width=1, border_color="#CCCCCC")
        self.log_area.pack(pady=(0, 10), padx=20, fill="x")
        self.log_area.configure(state="disabled")

        self.protocol('WM_DELETE_WINDOW', self.hide_window)
        self.setup_tray()
        threading.Thread(target=self.background_cleanup, daemon=True).start()

    def background_cleanup(self):
        self.log("啟動背景資料庫瘦身與檢查...")
        self.db.cleanup_ghost_records()
        self.log("資料庫檢查完成！")

    def log(self, msg):
        self.after(0, lambda: (self.log_area.configure(state="normal"), 
                               self.log_area.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n"), 
                               self.log_area.see("end"), 
                               self.log_area.configure(state="disabled")))

    def toggle_all(self):
        if not self.running:
            self.running = True
            self.btn_master.configure(text="🛑 停止系統監控", fg_color="#E63946", border_color="#B71C1C")
            threading.Thread(target=self.main_worker, daemon=True).start()
        else:
            self.running = False
            self.btn_master.configure(text="啟動全方位監控系統", fg_color="#1F6AA5", border_color="#154c79")
            self.log("🛑 任務已手動暫停")

    def main_worker(self):
        while self.running:
            self.gphoto_ui.run_tasks()
            self.sync_ui.run_tasks()
            for _ in range(60):
                if not self.running: break
                time.sleep(1)

    # 🚀 檢查目前是否已設定開機啟動
    def is_autostart_enabled(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, APP_NAME_REG)
            winreg.CloseKey(key)
            return True
        except WindowsError:
            return False

    # 🚀 切換開機啟動狀態 (Tray Menu 觸發)
    def toggle_autostart(self, icon, item):
        enabled = self.is_autostart_enabled()
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
            if enabled:
                # 若已經開啟，則刪除機碼 (關閉開機啟動)
                winreg.DeleteValue(key, APP_NAME_REG)
                self.log("ℹ️ 已取消開機自動啟動")
            else:
                # 若未開啟，則寫入執行檔路徑
                if getattr(sys, 'frozen', False):
                    # 若為 PyInstaller 打包的 EXE
                    exe_path = f'"{sys.executable}"'
                else:
                    # 若為開發環境運行 python main.py
                    exe_path = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
                
                winreg.SetValueEx(key, APP_NAME_REG, 0, winreg.REG_SZ, exe_path)
                self.log("ℹ️ 已設定開機自動啟動")
            winreg.CloseKey(key)
        except Exception as e:
            self.log(f"❌ 設定開機啟動失敗: {e}")

    def setup_tray(self):
        img = Image.new('RGB', (64, 64), (31, 106, 165))
        
        # 🚀 在常駐選單中加入「開機自動啟動」的勾選項
        menu = pystray.Menu(
            pystray.MenuItem('顯示面板', self.show_window, default=True),
            pystray.MenuItem('開機自動啟動', self.toggle_autostart, checked=lambda item: self.is_autostart_enabled()),
            pystray.MenuItem('退出', self.quit_sys)
        )
        
        self.tray = pystray.Icon("GPhotoUP", img, "GPhotoUP Pro", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def hide_window(self): self.withdraw()
    def show_window(self): self.deiconify(); self.focus_force()
    def quit_sys(self): self.running = False; self.tray.stop(); self.destroy(); sys.exit(0)

if __name__ == "__main__":
    app = GPhotoUPPro()
    app.mainloop()
