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

# 視窗標題名稱 (防重複開啟與尋找視窗使用)
WINDOW_TITLE = "GPhotoUP Pro - 多路徑雙帳號監控版"

# --- 1. 防重複開啟檢查 (Mutex) ---
mutex = win32event.CreateMutex(None, False, "Global\\GPhotoUP_Pro_SingleInstance")
if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
    hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    sys.exit(0)

# --- 2. 高 DPI 抗模糊設定 ---
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except: pass

# --- UI 佈景主題設定 ---
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# --- 核心參數設定 ---
SCOPES = ['https://www.googleapis.com/auth/photoslibrary']
UPLOAD_URL = 'https://photoslibrary.googleapis.com/v1/uploads'
APP_NAME = "GPhotoUP_Pro_Secure"
KEY_ID = "MultiTaskKey"
# 擴充支援的圖片與影片格式
SUPPORTED_FORMATS = ('.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif', '.mp4', '.mov', '.avi')

def get_base_path():
    """取得執行檔或腳本所在的真實資料夾路徑"""
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def create_tray_icon():
    """繪製右下角常駐系統匣的圖示"""
    img = Image.new('RGB', (64, 64), color=(52, 199, 89))
    draw = ImageDraw.Draw(img)
    draw.rectangle((16, 16, 48, 48), fill=(255, 255, 255))
    return img

# --- 資料庫管理 (斷點續傳、本地去重、記憶監控路徑) ---
class DBManager:
    def __init__(self):
        self.db_path = os.path.join(get_base_path(), "sync_history.db")
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # 照片上傳紀錄表
            conn.execute('''CREATE TABLE IF NOT EXISTS uploads 
                            (file_path TEXT, mtime REAL, size INTEGER, task_id TEXT, 
                             PRIMARY KEY(file_path, task_id))''')
            # 監控資料夾清單表
            conn.execute('''CREATE TABLE IF NOT EXISTS watch_paths 
                            (path TEXT, task_id TEXT, PRIMARY KEY(path, task_id))''')

    # [新增] 讀取某個任務的所有監控路徑
    def get_watch_paths(self, task_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT path FROM watch_paths WHERE task_id=?", (task_id,))
            return [row[0] for row in cursor.fetchall()]

    # [新增] 新增監控路徑
    def add_watch_path(self, path, task_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO watch_paths VALUES (?, ?)", (path, task_id))

    # [新增] 移除監控路徑
    def remove_watch_path(self, path, task_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM watch_paths WHERE path=? AND task_id=?", (path, task_id))

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

# --- 多路徑任務介面卡片 ---
class TaskManagerFrame(ctk.CTkFrame):
    def __init__(self, master, task_id, app_instance):
        super().__init__(master, corner_radius=15)
        self.task_id = task_id
        self.app = app_instance
        self.creds_path = ""

        # UI 標題與憑證載入
        self.label = ctk.CTkLabel(self, text=f"Google 帳號 {task_id}", font=ctk.CTkFont(size=16, weight="bold"))
        self.label.pack(pady=5)

        self.btn_creds = ctk.CTkButton(self, text="1. 載入 API 憑證 (JSON)", command=self.load_creds, height=30)
        self.btn_creds.pack(pady=5, padx=20)
        
        self.status_lbl = ctk.CTkLabel(self, text="尚未載入憑證", text_color="#FF3B30", font=ctk.CTkFont(size=12))
        self.status_lbl.pack(pady=(0, 10))

        # 監控資料夾列表
        ctk.CTkLabel(self, text="監控路徑清單:", font=ctk.CTkFont(size=13)).pack(anchor="w", padx=25)
        self.path_listbox = tk.Listbox(self, height=5, font=("Arial", 10))
        self.path_listbox.pack(pady=5, padx=20, fill="x")

        # 列表操作按鈕 (新增/刪除)
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkButton(btn_frame, text="＋ 新增路徑", width=80, command=self.add_path, fg_color="#5ac8fa").pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="－ 刪除選取", width=80, command=self.remove_path, fg_color="#FF3B30", hover_color="#D70015").pack(side="right", padx=5)

        self.sync_lbl = ctk.CTkLabel(self, text="待命中", text_color="gray", font=ctk.CTkFont(size=13))
        self.sync_lbl.pack(pady=10)

        # 初始化時載入資料庫中的路徑
        self.refresh_list()

    def load_creds(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if path: 
            self.creds_path = path
            self.update_status("憑證已準備就緒", "#34c759", is_auth=True)

    def refresh_list(self):
        self.path_listbox.delete(0, tk.END)
        for p in self.app.db.get_watch_paths(self.task_id):
            self.path_listbox.insert(tk.END, p)

    def add_path(self):
        path = filedialog.askdirectory(title="選擇要監控的母資料夾")
        if path:
            self.app.db.add_watch_path(path, self.task_id)
            self.refresh_list()

    def remove_path(self):
        selected = self.path_listbox.curselection()
        if selected:
            path = self.path_listbox.get(selected[0])
            self.app.db.remove_watch_path(path, self.task_id)
            self.refresh_list()

    def update_status(self, text, color="gray", is_auth=False):
        self.app.after(0, lambda: (self.status_lbl if is_auth else self.sync_lbl).configure(text=text, text_color=color))

# --- 主程式視窗 ---
class GPhotoUPPro(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("850x800")
        
        self.db = DBManager()
        self.fernet = self.init_cipher()
        self.running = False

        # --- UI 佈局 ---
        self.grid_columnconfigure((0, 1), weight=1)
        
        self.task_a = TaskManagerFrame(self, "A", self)
        self.task_a.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.task_b = TaskManagerFrame(self, "B", self)
        self.task_b.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        self.autostart_var = ctk.BooleanVar(value=self.check_autostart())
        self.switch_autostart = ctk.CTkSwitch(self, text="電腦開機時自動啟動程式", variable=self.autostart_var, command=self.toggle_autostart)
        self.switch_autostart.grid(row=1, column=0, columnspan=2, pady=10)

        self.btn_master = ctk.CTkButton(self, text="啟動全方位監控同步", command=self.toggle_all, height=50, font=ctk.CTkFont(size=18, weight="bold"), fg_color="#34c759")
        self.btn_master.grid(row=2, column=0, columnspan=2, pady=10, padx=40, sticky="ew")

        self.log_area = ctk.CTkTextbox(self, height=200, font=ctk.CTkFont(family="Consolas", size=13))
        self.log_area.grid(row=3, column=0, columnspan=2, pady=10, padx=20, sticky="nsew")
        self.log_area.configure(state="disabled")

        # 設定關閉視窗的行為與系統列
        self.protocol('WM_DELETE_WINDOW', self.hide_window)
        self.setup_system_tray()

    # --- 開機啟動與常駐邏輯 ---
    def check_autostart(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, "GPhotoUP")
            winreg.CloseKey(key)
            return True
        except: return False

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

    def setup_system_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem('開啟控制面板', self.show_window, default=True),
            pystray.MenuItem('完全退出程式', self.quit_program)
        )
        self.tray_icon = pystray.Icon("GPhotoUP", create_tray_icon(), "Google 相簿同步", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_window(self):
        self.withdraw()
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.notify("已縮小至右下角", "程式仍在背景監控相簿上傳")

    def show_window(self, icon=None, item=None):
        self.after(0, self._show_window)

    def _show_window(self):
        self.deiconify()
        self.focus_force()

    def quit_program(self, icon, item):
        self.running = False
        self.tray_icon.stop()
        self.destroy()
        sys.exit(0)

    # --- 加密金鑰 Fallback 防呆機制 ---
    def init_cipher(self):
        try:
            key = keyring.get_password(APP_NAME, KEY_ID)
            if not key:
                key = Fernet.generate_key().decode()
                keyring.set_password(APP_NAME, KEY_ID, key)
            return Fernet(key.encode())
        except Exception:
            key_file = os.path.join(get_base_path(), ".secret.key")
            if os.path.exists(key_file):
                with open(key_file, "rb") as f: return Fernet(f.read())
            else:
                key = Fernet.generate_key()
                with open(key_file, "wb") as f: f.write(key)
                return Fernet(key)

    def log(self, msg):
        self.after(0, lambda: self._log_ui(msg))

    def _log_ui(self, msg):
        self.log_area.configure(state="normal")
        self.log_area.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log_area.see("end")
        self.log_area.configure(state="disabled")

    # --- 核心同步邏輯 (支援多路徑掃描) ---
    def toggle_all(self):
        if not self.running:
            paths_a = self.db.get_watch_paths(self.task_a.task_id)
            paths_b = self.db.get_watch_paths(self.task_b.task_id)
            
            if not paths_a and not paths_b:
                messagebox.showwarning("提示", "請至少為一個帳號新增要監控的資料夾路徑。")
                return

            self.running = True
            self.btn_master.configure(text="停止監控 (背景執行中)", fg_color="#FF3B30")
            self.log("🚀 啟動多路徑監控任務...")
            
            if paths_a: self.task_a.update_status("掃描監控中", "#ff9500")
            if paths_b: self.task_b.update_status("掃描監控中", "#ff9500")
            
            threading.Thread(target=self.main_loop, daemon=True).start()
        else:
            self.running = False
            self.btn_master.configure(text="啟動全方位監控同步", fg_color="#34c759")
            self.task_a.update_status("已暫停", "gray")
            self.task_b.update_status("已暫停", "gray")
            self.log("🛑 任務已暫停")

    def main_loop(self):
        while self.running:
            for task in [self.task_a, self.task_b]:
                paths = self.db.get_watch_paths(task.task_id)
                if self.running and paths: 
                    self.process_task(task, paths)
            for _ in range(60): # 每一分鐘循環掃描一次
                if not self.running: break
                time.sleep(1)

    def process_task(self, task, watch_paths):
        creds = self.auth_task(task)
        if not creds: return
        service = build('photoslibrary', 'v1', credentials=creds, static_discovery=False)
        
        for root_path in watch_paths:
            if not os.path.exists(root_path): continue
            
            # 掃描每個監控路徑下的子資料夾 (這些子資料夾名稱會變成相簿名稱)
            for folder_name in os.listdir(root_path):
                folder_path = os.path.join(root_path, folder_name)
                if os.path.isdir(folder_path) and self.running:
                    album_id = self.get_or_create_album(service, folder_name)
                    if not album_id: continue
                    
                    for f in os.listdir(folder_path):
                        f_path = os.path.join(folder_path, f)
                        if f.lower().endswith(SUPPORTED_FORMATS) and not self.db.is_uploaded(f_path, task.task_id):
                            if not self.running: break
                            
                            task.update_status(f"上傳中: {f[:15]}...", "#34c759")
                            
                            token = self.upload_raw(f_path, creds.token, task.task_id)
                            if token and self.bind_to_album(service, token, album_id):
                                self.db.mark_as_uploaded(f_path, task.task_id)
                                self.log(f"[{task.task_id}] ✔️ 成功: {f}")
                            else:
                                self.log(f"[{task.task_id}] ⚠️ 網路不穩，跳過: {f} (將於下次重試)")
                                
        if self.running: task.update_status("掃描監控中 (閒置待命)", "#ff9500")

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
        # 授權成功後，更新 UI 狀態
        if creds and creds.valid:
            task.update_status("授權已完成", "#34c759", is_auth=True)
        return creds

    def get_or_create_album(self, service, title):
        try: return service.albums().create(body={'album': {'title': title}}).execute().get('id')
        except: return None

    # --- 指數退避重試機制 (解決大檔案影片上傳逾時) ---
    def upload_raw(self, path, token, task_id, max_retries=3):
        headers = {'Authorization': f'Bearer {token}', 'Content-type': 'application/octet-stream',
                   'X-Goog-Upload-Protocol': 'raw', 'X-Goog-File-Name': os.path.basename(path).encode('utf-8').decode('latin-1')}
        for attempt in range(max_retries):
            try:
                with open(path, 'rb') as f:
                    r = requests.post(UPLOAD_URL, data=f.read(), headers=headers, timeout=120)
                    if r.status_code == 200: return r.text
            except Exception:
                pass 
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                self.log(f"[{task_id}] 連線波動，{wait_time} 秒後進行第 {attempt+2} 次重試...")
                time.sleep(wait_time)
        return None

    def bind_to_album(self, service, upload_token, album_id):
        for attempt in range(2):
            try:
                service.mediaItems().batchCreate(body={'newMediaItems': [{'simpleMediaItem': {'uploadToken': upload_token}}], 'albumId': album_id}).execute()
                return True
            except:
                time.sleep(2)
        return False

if __name__ == "__main__":
    app = GPhotoUPPro()
    app.mainloop()
