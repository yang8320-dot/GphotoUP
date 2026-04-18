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
from cryptography.fernet import Fernet
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import customtkinter as ctk

# --- 高 DPI 與 iOS 風格設定 ---
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

# --- 資料庫管理類別 ---
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

# --- 單一任務 UI 組件 ---
class SyncTaskFrame(ctk.CTkFrame):
    def __init__(self, master, task_id, app_instance):
        super().__init__(master, corner_radius=15)
        self.task_id = task_id
        self.app = app_instance
        self.creds_path = ""
        self.target_dir = ""
        self.running = False

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

# --- 主程式 ---
class GPhotoUPV2(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("GPhotoUP V2 - 雙向監控續傳版")
        self.geometry("800x700")
        
        self.db = DBManager()
        self.fernet = self.init_cipher()

        # UI 佈局
        self.grid_columnconfigure((0, 1), weight=1)
        
        self.task_a = SyncTaskFrame(self, "A", self)
        self.task_a.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.task_b = SyncTaskFrame(self, "B", self)
        self.task_b.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        self.btn_master = ctk.CTkButton(self, text="啟動雙重監控任務", command=self.toggle_all, 
                                        height=50, font=ctk.CTkFont(size=18, weight="bold"), fg_color="#34c759")
        self.btn_master.pack(pady=20, padx=40, fill="x")

        self.log_area = ctk.CTkTextbox(self, height=250)
        self.log_area.pack(pady=10, padx=20, fill="both")
        self.log_area.configure(state="disabled")

        self.running = False

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

    def toggle_all(self):
        if not self.running:
            if not (self.task_a.target_dir and self.task_b.target_dir):
                messagebox.showwarning("警告", "請確保兩個任務的資料夾都已選取")
                return
            self.running = True
            self.btn_master.configure(text="停止監控", fg_color="#FF3B30")
            threading.Thread(target=self.main_loop, daemon=True).start()
        else:
            self.running = False
            self.btn_master.configure(text="啟動雙重監控任務", fg_color="#34c759")

    def main_loop(self):
        while self.running:
            self.log("🔄 開始輪詢掃描...")
            for task in [self.task_a, self.task_b]:
                if self.running:
                    self.process_task(task)
            self.log("💤 掃描完成，等待 60 秒後再次檢查...")
            for _ in range(60):
                if not self.running: break
                time.sleep(1)

    def process_task(self, task):
        # 1. 驗證 (每個任務獨立 Token)
        creds = self.auth_task(task)
        if not creds: return
        
        service = build('photoslibrary', 'v1', credentials=creds, static_discovery=False)
        
        # 2. 掃描
        for folder_name in os.listdir(task.target_dir):
            folder_path = os.path.join(task.target_dir, folder_name)
            if os.path.isdir(folder_path) and self.running:
                # 建立相簿
                album_id = self.get_or_create_album(service, folder_name)
                if not album_id: continue
                
                for f in os.listdir(folder_path):
                    f_path = os.path.join(folder_path, f)
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.heic')) and not self.db.is_uploaded(f_path, task.task_id):
                        self.log(f"[{task.task_id}] 準備上傳: {f}")
                        token = self.upload_raw(f_path, creds.token)
                        if token:
                            if self.bind_to_album(service, token, album_id):
                                self.db.mark_as_uploaded(f_path, task.task_id)
                                self.log(f"[{task.task_id}] ✔️ 成功: {f}")
                            else:
                                self.log(f"[{task.task_id}] ❌ 綁定相簿失敗: {f}")
                        else:
                            self.log(f"[{task.task_id}] ⚠️ 上傳失敗（可能是網路中斷），跳過此檔")

    def auth_task(self, task):
        token_path = os.path.join(get_base_path(), f"token_{task.task_id}.enc")
        creds = None
        if os.path.exists(token_path):
            try:
                with open(token_path, 'rb') as f:
                    creds = pickle.loads(self.fernet.decrypt(f.read()))
            except: pass

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try: creds.refresh(Request())
                except: creds = None
            
            if not creds:
                if not task.creds_path: return None
                flow = InstalledAppFlow.from_client_secrets_file(task.creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(token_path, 'wb') as f:
                f.write(self.fernet.encrypt(pickle.dumps(creds)))
        return creds

    def get_or_create_album(self, service, title):
        try:
            # 簡化版：直接建立，API 會自動處理同名或重複
            res = service.albums().create(body={'album': {'title': title}}).execute()
            return res.get('id')
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
            body = {'newMediaItems': [{'simpleMediaItem': {'uploadToken': upload_token}}], 'albumId': album_id}
            service.mediaItems().batchCreate(body=body).execute()
            return True
        except: return False

if __name__ == "__main__":
    app = GPhotoUPV2()
    app.mainloop()
