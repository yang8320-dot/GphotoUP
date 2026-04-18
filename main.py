import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import pickle
import requests
import sqlite3
import time
import keyring
import winreg
from cryptography.fernet import Fernet
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import customtkinter as ctk

# --- 系統底層與常駐模組 ---
import pystray
from PIL import Image, ImageDraw
import win32event
import win32api
import winerror
import win32gui
import win32con

# 視窗標題名稱 (必須固定，尋找視窗時會用到)
WINDOW_TITLE = "GPhotoUP V2 - 雙向監控續傳版"

# --- 防重複開啟檢查 (Mutex) ---
mutex = win32event.CreateMutex(None, False, "Global\\GPhotoUP_V2_SingleInstance")
if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
    # 如果已經開啟，找到舊視窗並把它移到最前面
    hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    sys.exit(0) # 結束這個新的實例

# --- 高 DPI 設定 ---
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except: pass

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

SCOPES = ['https://www.googleapis.com/auth/photoslibrary']
UPLOAD_URL = 'https://photoslibrary.googleapis.com/v1/uploads'
APP_NAME = "GPhotoUP_V2_Secure"
KEY_ID = "MultiTaskKey"

def get_base_path():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def create_tray_icon():
    """用程式碼畫一個簡單的綠色圖示，不用另外準備圖片檔"""
    img = Image.new('RGB', (64, 64), color=(52, 199, 89))
    draw = ImageDraw.Draw(img)
    draw.rectangle((16, 16, 48, 48), fill=(255, 255, 255))
    return img

class DBManager:
    def __init__(self):
        self.db_path = os.path.join(get_base_path(), "sync_history.db")
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS uploads 
                            (file_path TEXT, mtime REAL, size INTEGER, task_id TEXT, 
                             PRIMARY KEY(file_path, task_id))''')

    def is_uploaded(self, file_path, task_id):
        if not os.path.exists(file_path): return True
        stat = os.stat(file_path)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM uploads WHERE file_path=? AND mtime=? AND size=? AND task_id=?", 
                                  (file_path, stat.st_mtime, stat.st_size, task_id))
            return cursor.fetchone() is not None

    def mark_as_uploaded(self, file_path, task_id):
        stat = os.stat(file_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO uploads VALUES (?, ?, ?, ?)", 
                          (file_path, stat.st_mtime, stat.st_size, task_id))

class SyncTaskFrame(ctk.CTkFrame):
    def __init__(self, master, task_id, app_instance):
        super().__init__(master, corner_radius=15)
        self.task_id = task_id
        self.app = app_instance
        self.creds_path = ""
        self.target_dir = ""

        self.label = ctk.CTkLabel(self, text=f"任務 {task_id}", font=ctk.CTkFont(size=16, weight="bold"))
        self.label.pack(pady=5)

        self.btn_creds = ctk.CTkButton(self, text="載入憑證 (JSON)", command=self.load_creds, height=30)
        self.btn_creds.pack(pady=5, padx=20)

        self.btn_dir = ctk.CTkButton(self, text="指定資料夾", command=self.load_dir, height=30, fg_color="#5ac8fa")
        self.btn_dir.pack(pady=5, padx=20)

        self.status_lbl = ctk.CTkLabel(self, text="待命中", text_color="gray", font=ctk.CTkFont(size=12))
        self.status_lbl.pack(pady=5)

    def load_creds(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if path: 
            self.creds_path = path
            self.status_lbl.configure(text="憑證已載入", text_color="#34c759")

    def load_dir(self):
        path = filedialog.askdirectory()
        if path: 
            self.target_dir = path
            self.status_lbl.configure(text=f"已選: {os.path.basename(path)}", text_color="#007AFF")

class GPhotoUPV2(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("800x750")
        
        self.db = DBManager()
        self.fernet = self.init_cipher()
        self.running = False

        # --- UI 佈局 ---
        self.grid_columnconfigure((0, 1), weight=1)
        
        self.task_a = SyncTaskFrame(self, "A", self)
        self.task_a.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.task_b = SyncTaskFrame(self, "B", self)
        self.task_b.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        # 開機啟動開關
        self.autostart_var = ctk.BooleanVar(value=self.check_autostart())
        self.switch_autostart = ctk.CTkSwitch(self, text="電腦開機時自動啟動程式", 
                                              variable=self.autostart_var, command=self.toggle_autostart)
        self.switch_autostart.grid(row=1, column=0, columnspan=2, pady=10)

        self.btn_master = ctk.CTkButton(self, text="啟動雙重監控任務", command=self.toggle_all, 
                                        height=50, font=ctk.CTkFont(size=18, weight="bold"), fg_color="#34c759")
        self.btn_master.grid(row=2, column=0, columnspan=2, pady=10, padx=40, sticky="ew")

        self.log_area = ctk.CTkTextbox(self, height=250)
        self.log_area.grid(row=3, column=0, columnspan=2, pady=10, padx=20, sticky="nsew")
        self.log_area.configure(state="disabled")

        # --- 系統匣與視窗事件設定 ---
        self.protocol('WM_DELETE_WINDOW', self.hide_window) # 按右上角叉叉時，改為縮小到右下角
        self.setup_system_tray()

    # --- 開機自動啟動邏輯 (寫入 Windows 登錄檔) ---
    def check_autostart(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, "GPhotoUP")
            winreg.CloseKey(key)
            return True
        except WindowsError:
            return False

    def toggle_autostart(self):
        enable = self.autostart_var.get()
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
        if enable:
            winreg.SetValueEx(key, "GPhotoUP", 0, winreg.REG_SZ, exe_path)
            self.log("🔧 已開啟：開機自動啟動")
        else:
            try: winreg.DeleteValue(key, "GPhotoUP")
            except: pass
            self.log("🔧 已關閉：開機自動啟動")
        winreg.CloseKey(key)

    # --- 常駐系統匣邏輯 (右下角圖示) ---
    def setup_system_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem('開啟控制面板', self.show_window, default=True),
            pystray.MenuItem('完全退出程式', self.quit_program)
        )
        self.tray_icon = pystray.Icon("GPhotoUP", create_tray_icon(), "Google 相簿同步", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_window(self):
        self.withdraw() # 隱藏視窗
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.notify("已縮小至右下角", "程式仍在背景監控相簿上傳")

    def show_window(self, icon=None, item=None):
        self.after(0, self._show_window)

    def _show_window(self):
        self.deiconify() # 顯示視窗
        self.focus_force() # 強制提到最前面

    def quit_program(self, icon, item):
        self.running = False
        self.tray_icon.stop()
        self.destroy()
        sys.exit(0)

    # --- 加密與授權邏輯 ---
    def init_cipher(self):
        key = keyring.get_password(APP_NAME, KEY_ID)
        if not key:
            key = Fernet.generate_key().decode()
            keyring.set_password(APP_NAME, KEY_ID, key)
        return Fernet(key.encode())

    def log(self, msg):
        self.after(0, lambda: self._log_ui(msg))

    def _log_ui(self, msg):
        self.log_area.configure(state="normal")
        self.log_area.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log_area.see("end")
        self.log_area.configure(state="disabled")

    # --- 核心同步邏輯 ---
    def toggle_all(self):
        if not self.running:
            if not (self.task_a.target_dir and self.task_b.target_dir):
                messagebox.showwarning("警告", "請確保兩個任務的資料夾都已選取")
                return
            self.running = True
            self.btn_master.configure(text="停止監控 (背景執行中)", fg_color="#FF3B30")
            self.log("🚀 啟動雙重監控任務...")
            threading.Thread(target=self.main_loop, daemon=True).start()
        else:
            self.running = False
            self.btn_master.configure(text="啟動雙重監控任務", fg_color="#34c759")
            self.log("🛑 任務已暫停")

    def main_loop(self):
        while self.running:
            for task in [self.task_a, self.task_b]:
                if self.running: self.process_task(task)
            for _ in range(60):
                if not self.running: break
                time.sleep(1)

    def process_task(self, task):
        creds = self.auth_task(task)
        if not creds: return
        service = build('photoslibrary', 'v1', credentials=creds, static_discovery=False)
        for folder_name in os.listdir(task.target_dir):
            folder_path = os.path.join(task.target_dir, folder_name)
            if os.path.isdir(folder_path) and self.running:
                album_id = self.get_or_create_album(service, folder_name)
                if not album_id: continue
                for f in os.listdir(folder_path):
                    f_path = os.path.join(folder_path, f)
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.heic')) and not self.db.is_uploaded(f_path, task.task_id):
                        token = self.upload_raw(f_path, creds.token)
                        if token and self.bind_to_album(service, token, album_id):
                            self.db.mark_as_uploaded(f_path, task.task_id)
                            self.log(f"[{task.task_id}] ✔️ 成功: {f}")
                        else:
                            self.log(f"[{task.task_id}] ⚠️ 失敗: {f}")

    def auth_task(self, task):
        token_path = os.path.join(get_base_path(), f"token_{task.task_id}.enc")
        creds = None
        if os.path.exists(token_path):
            try:
                with open(token_path, 'rb') as f: creds = pickle.loads(self.fernet.decrypt(f.read()))
            except: pass
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try: creds.refresh(Request())
                except: creds = None
            if not creds:
                if not task.creds_path: return None
                flow = InstalledAppFlow.from_client_secrets_file(task.creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, 'wb') as f: f.write(self.fernet.encrypt(pickle.dumps(creds)))
        return creds

    def get_or_create_album(self, service, title):
        try: return service.albums().create(body={'album': {'title': title}}).execute().get('id')
        except: return None

    def upload_raw(self, path, token):
        headers = {'Authorization': f'Bearer {token}', 'Content-type': 'application/octet-stream',
                   'X-Goog-Upload-Protocol': 'raw', 'X-Goog-File-Name': os.path.basename(path).encode('utf-8').decode('latin-1')}
        try:
            with open(path, 'rb') as f:
                r = requests.post(UPLOAD_URL, data=f.read(), headers=headers, timeout=30)
                return r.text if r.status_code == 200 else None
        except: return None

    def bind_to_album(self, service, upload_token, album_id):
        try:
            service.mediaItems().batchCreate(body={'newMediaItems': [{'simpleMediaItem': {'uploadToken': upload_token}}], 'albumId': album_id}).execute()
            return True
        except: return False

if __name__ == "__main__":
    app = GPhotoUPV2()
    app.mainloop()
