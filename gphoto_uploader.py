import os
import sys
import pickle
import time
import requests
import sqlite3
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
import keyring
from cryptography.fernet import Fernet
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/photoslibrary']
UPLOAD_URL = 'https://photoslibrary.googleapis.com/v1/uploads'
SUPPORTED_FORMATS = ('.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif', '.mp4', '.mov', '.avi')
APP_NAME = "GPhotoUP_System"
KEY_ID = "MasterKey"

def get_base_path():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# --- 資料庫管理器 ---
class DBManager:
    def __init__(self):
        self.db_path = os.path.join(get_base_path(), "system_data.db")
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS uploads (file_path TEXT, mtime REAL, size INTEGER, task_id TEXT, PRIMARY KEY(file_path, task_id))')
            conn.execute('CREATE TABLE IF NOT EXISTS watch_paths (path TEXT, task_id TEXT, PRIMARY KEY(path, task_id))')
            conn.execute('CREATE TABLE IF NOT EXISTS task_settings (task_id TEXT PRIMARY KEY, task_name TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS sync_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, target TEXT, bw_limit TEXT)')

    # ✨ 資料庫自動瘦身機制
    def cleanup_ghost_records(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT file_path, task_id FROM uploads")
                records = cursor.fetchall()
                # 找出實體檔案已經不存在的紀錄
                ghosts = [(path, tid) for path, tid in records if not os.path.exists(path)]
                if ghosts:
                    conn.executemany("DELETE FROM uploads WHERE file_path=? AND task_id=?", ghosts)
                    conn.execute("VACUUM") # 釋放硬碟空間
        except Exception as e:
            pass

    def get_task_name(self, tid):
        with sqlite3.connect(self.db_path) as conn:
            res = conn.execute("SELECT task_name FROM task_settings WHERE task_id=?", (tid,)).fetchone()
            return res[0] if res else f"Google 帳號 {tid}"

    def set_task_name(self, tid, name):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO task_settings VALUES (?, ?)", (tid, name))

    def get_watch_paths(self, tid):
        with sqlite3.connect(self.db_path) as conn:
            return [row[0] for row in conn.execute("SELECT path FROM watch_paths WHERE task_id=?", (tid,)).fetchall()]

    def add_watch_path(self, path, tid):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO watch_paths VALUES (?, ?)", (path, tid))

    def remove_watch_path(self, path, tid):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM watch_paths WHERE path=? AND task_id=?", (path, tid))

    def is_uploaded(self, fp, tid):
        if not os.path.exists(fp): return True
        s = os.stat(fp)
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT 1 FROM uploads WHERE file_path=? AND mtime=? AND size=? AND task_id=?", (fp, s.st_mtime, s.st_size, tid)).fetchone() is not None

    def mark_uploaded(self, fp, tid):
        s = os.stat(fp)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO uploads VALUES (?, ?, ?, ?)", (fp, s.st_mtime, s.st_size, tid))

    # Sync DB Methods
    def get_sync_tasks(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT id, source, target, bw_limit FROM sync_tasks").fetchall()

    def add_sync_task(self, src, tgt, bw):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO sync_tasks (source, target, bw_limit) VALUES (?, ?, ?)", (src, tgt, bw))

    def delete_sync_task(self, tid):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM sync_tasks WHERE id=?", (tid,))

# --- Google 相簿 UI 與任務邏輯 ---
class GphotoTaskFrame(ctk.CTkFrame):
    def __init__(self, master, tid, app):
        super().__init__(master, corner_radius=15)
        self.tid = tid
        self.app = app
        self.creds_path = ""

        # 自訂名稱輸入
        self.name_var = tk.StringVar(value=self.app.db.get_task_name(tid))
        self.entry_name = ctk.CTkEntry(self, textvariable=self.name_var, font=ctk.CTkFont(size=16, weight="bold"), justify="center", border_width=1, corner_radius=8, fg_color="transparent")
        self.entry_name.pack(pady=(15, 5), padx=20, fill="x")
        self.entry_name.bind("<FocusOut>", self.save_task_name)
        self.entry_name.bind("<Return>", self.save_task_name)

        self.btn_creds = ctk.CTkButton(self, text="載入 API 憑證 (JSON)", command=self.load_creds, height=30)
        self.btn_creds.pack(pady=5, padx=20)
        
        self.status_lbl = ctk.CTkLabel(self, text="尚未載入憑證", text_color="#FF3B30", font=ctk.CTkFont(size=12))
        self.status_lbl.pack(pady=(0, 10))

        # 監控資料夾列表
        ctk.CTkLabel(self, text="監控路徑清單:", font=ctk.CTkFont(size=13)).pack(anchor="w", padx=25)
        self.path_listbox = tk.Listbox(self, height=5, font=("Arial", 10))
        self.path_listbox.pack(pady=5, padx=20, fill="x")

        # 列表操作按鈕
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkButton(btn_frame, text="＋ 新增", width=60, command=self.add_path, fg_color="#5ac8fa").pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="－ 刪除", width=60, command=self.remove_path, fg_color="#FF3B30").pack(side="right", padx=5)

        self.sync_lbl = ctk.CTkLabel(self, text="待命中", text_color="gray", font=ctk.CTkFont(size=13))
        self.sync_lbl.pack(pady=10)
        self.refresh_list()

    def save_task_name(self, event=None):
        new_name = self.name_var.get().strip() or f"Google 帳號 {self.tid}"
        self.name_var.set(new_name)
        self.app.db.set_task_name(self.tid, new_name)
        self.app.focus_set()

    def load_creds(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if path: 
            self.creds_path = path
            self.update_status("憑證已準備就緒", "#34c759", is_auth=True)

    def refresh_list(self):
        self.path_listbox.delete(0, tk.END)
        for p in self.app.db.get_watch_paths(self.tid): self.path_listbox.insert(tk.END, p)

    def add_path(self):
        p = filedialog.askdirectory(title="選擇要監控的母資料夾")
        if p: self.app.db.add_watch_path(p, self.tid); self.refresh_list()

    def remove_path(self):
        selected = self.path_listbox.curselection()
        if selected:
            self.app.db.remove_watch_path(self.path_listbox.get(selected[0]), self.tid)
            self.refresh_list()

    def update_status(self, text, color="gray", is_auth=False):
        self.app.after(0, lambda: (self.status_lbl if is_auth else self.sync_lbl).configure(text=text, text_color=color))


class GphotoComponent(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure((0, 1), weight=1)
        self.fernet = self.init_cipher()
        
        self.frame_a = GphotoTaskFrame(self, "A", app)
        self.frame_a.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.frame_b = GphotoTaskFrame(self, "B", app)
        self.frame_b.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

    def init_cipher(self):
        try:
            k = keyring.get_password(APP_NAME, KEY_ID)
            if not k: k = Fernet.generate_key().decode(); keyring.set_password(APP_NAME, KEY_ID, k)
            return Fernet(k.encode())
        except: return Fernet(Fernet.generate_key())

    def run_tasks(self):
        for frame in [self.frame_a, self.frame_b]:
            paths = self.app.db.get_watch_paths(frame.tid)
            if paths: self.process_task(frame, paths)

    def process_task(self, frame, paths):
        creds = self.auth_task(frame)
        if not creds: return
        service = build('photoslibrary', 'v1', credentials=creds, static_discovery=False)
        for root_path in paths:
            if not os.path.exists(root_path): continue
            for folder_name in os.listdir(root_path):
                folder_path = os.path.join(root_path, folder_name)
                if os.path.isdir(folder_path) and self.app.running:
                    album_id = self.get_or_create_album(service, folder_name)
                    if not album_id: continue
                    for f in os.listdir(folder_path):
                        f_path = os.path.join(folder_path, f)
                        if f.lower().endswith(SUPPORTED_FORMATS) and not self.app.db.is_uploaded(f_path, frame.tid):
                            if not self.app.running: break
                            frame.update_status(f"上傳中: {f[:15]}...", "#34c759")
                            token = self.upload_raw(f_path, creds.token, frame.name_var.get())
                            if token and self.bind_to_album(service, token, album_id):
                                self.app.db.mark_uploaded(f_path, frame.tid)
                                self.app.log(f"[{frame.name_var.get()}] ✔️ 成功: {f}")
                            else:
                                self.app.log(f"[{frame.name_var.get()}] ⚠️ 網路不穩跳過: {f}")
        if self.app.running: frame.update_status("掃描監控中", "#ff9500")

    def auth_task(self, frame):
        token_path = os.path.join(get_base_path(), f"token_{frame.tid}.enc")
        creds = None
        if os.path.exists(token_path):
            try:
                with open(token_path, 'rb') as f: creds = pickle.loads(self.fernet.decrypt(f.read()))
            except: pass
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
            elif frame.creds_path:
                flow = InstalledAppFlow.from_client_secrets_file(frame.creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            else: return None
            with open(token_path, 'wb') as f: f.write(self.fernet.encrypt(pickle.dumps(creds)))
        if creds and creds.valid: frame.update_status("授權已完成", "#34c759", is_auth=True)
        return creds

    def get_or_create_album(self, service, title):
        try: return service.albums().create(body={'album': {'title': title}}).execute().get('id')
        except: return None

    def upload_raw(self, path, token, log_name, max_retries=3):
        headers = {'Authorization': f'Bearer {token}', 'Content-type': 'application/octet-stream', 'X-Goog-Upload-Protocol': 'raw', 'X-Goog-File-Name': os.path.basename(path).encode('utf-8').decode('latin-1')}
        for attempt in range(max_retries):
            try:
                with open(path, 'rb') as f:
                    r = requests.post(UPLOAD_URL, data=f.read(), headers=headers, timeout=120)
                    if r.status_code == 200: return r.text
            except Exception: pass 
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                self.app.log(f"[{log_name}] 連線波動，{wait_time} 秒後重試...")
                time.sleep(wait_time)
        return None

    def bind_to_album(self, service, upload_token, album_id):
        for attempt in range(2):
            try:
                service.mediaItems().batchCreate(body={'newMediaItems': [{'simpleMediaItem': {'uploadToken': upload_token}}], 'albumId': album_id}).execute()
                return True
            except: time.sleep(2)
        return False
