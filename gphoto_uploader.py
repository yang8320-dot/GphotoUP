# --- START OF FILE gphoto_uploader.py ---
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
            
            # 🚀 自動升級舊版資料庫：檢查並新增 sync_mode 欄位
            cursor = conn.execute("PRAGMA table_info(sync_tasks)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'sync_mode' not in columns:
                conn.execute("ALTER TABLE sync_tasks ADD COLUMN sync_mode TEXT DEFAULT '單向同步'")

    def cleanup_ghost_records(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT file_path, task_id FROM uploads")
                records = cursor.fetchall()
                ghosts = [(path, tid) for path, tid in records if not os.path.exists(path)]
                if ghosts:
                    conn.executemany("DELETE FROM uploads WHERE file_path=? AND task_id=?", ghosts)
                    conn.execute("VACUUM")
        except: pass

    def is_uploaded_fast(self, fp, mtime, size, tid):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT 1 FROM uploads WHERE file_path=? AND mtime=? AND size=? AND task_id=?", (fp, mtime, size, tid)).fetchone() is not None

    def mark_uploaded_fast(self, fp, mtime, size, tid):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO uploads VALUES (?, ?, ?, ?)", (fp, mtime, size, tid))

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

    def get_sync_tasks(self):
        with sqlite3.connect(self.db_path) as conn:
            # 加入 COALESCE 確保舊任務預設為單向同步
            return conn.execute("SELECT id, source, target, bw_limit, COALESCE(sync_mode, '單向同步') FROM sync_tasks").fetchall()

    def add_sync_task(self, src, tgt, bw, mode):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO sync_tasks (source, target, bw_limit, sync_mode) VALUES (?, ?, ?, ?)", (src, tgt, bw, mode))

    def delete_sync_task(self, tid):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM sync_tasks WHERE id=?", (tid,))

class GphotoTaskFrame(ctk.CTkFrame):
    def __init__(self, master, tid, app):
        super().__init__(master, corner_radius=15, fg_color="transparent")
        self.tid, self.app, self.creds_path = tid, app, ""

        self.name_var = tk.StringVar(value=self.app.db.get_task_name(tid))
        self.entry_name = ctk.CTkEntry(self, textvariable=self.name_var, 
                                      font=("微軟正黑體", 18, "bold"), text_color=("#111111", "#FFFFFF"),
                                      justify="center", border_width=2, corner_radius=8, 
                                      fg_color=("#FFFFFF", "#2B2B2B"))
        self.entry_name.pack(pady=(15, 5), padx=20, fill="x")
        self.entry_name.bind("<FocusOut>", self.save_task_name)

        ctk.CTkButton(self, text="載入 API 憑證 (JSON)", font=("微軟正黑體", 13, "bold"), 
                      command=self.load_creds, height=35).pack(pady=5, padx=20)
        self.status_lbl = ctk.CTkLabel(self, text="尚未載入憑證", text_color="#E63946", font=("微軟正黑體", 13, "bold"))
        self.status_lbl.pack(pady=(0, 10))

        ctk.CTkLabel(self, text="監控路徑清單:", font=("微軟正黑體", 14, "bold"), text_color=("#333333", "#CCCCCC")).pack(anchor="w", padx=25)
        
        self.path_listbox = tk.Listbox(self, height=6, font=("微軟正黑體", 11), 
                                       bg="#FFFFFF", fg="#111111", borderwidth=1, relief="solid",
                                       selectbackground="#1F6AA5", selectforeground="#FFFFFF")
        self.path_listbox.pack(pady=5, padx=20, fill="x")

        btn_f = ctk.CTkFrame(self, fg_color="transparent")
        btn_f.pack(fill="x", padx=20, pady=5)
        ctk.CTkButton(btn_f, text="＋ 新增路徑", font=("微軟正黑體", 13, "bold"), command=self.add_path, fg_color="#2A9D8F").pack(side="left", padx=5)
        ctk.CTkButton(btn_f, text="－ 移除選取", font=("微軟正黑體", 13, "bold"), command=self.remove_path, fg_color="#E63946").pack(side="right", padx=5)

        self.sync_lbl = ctk.CTkLabel(self, text="待命中", text_color=("#555555", "#AAAAAA"), font=("微軟正黑體", 14, "bold"))
        self.sync_lbl.pack(pady=10)
        self.refresh_list()

    def save_task_name(self, e=None):
        self.app.db.set_task_name(self.tid, self.name_var.get())

    def load_creds(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if p: self.creds_path = p; self.update_status("憑證已備妥", "#2A9D8F", True)

    def refresh_list(self):
        self.path_listbox.delete(0, tk.END)
        for p in self.app.db.get_watch_paths(self.tid): self.path_listbox.insert(tk.END, p)

    def add_path(self):
        p = filedialog.askdirectory(); 
        if p: self.app.db.add_watch_path(p, self.tid); self.refresh_list()

    def remove_path(self):
        s = self.path_listbox.curselection()
        if s: self.app.db.remove_watch_path(self.path_listbox.get(s[0]), self.tid); self.refresh_list()

    def update_status(self, text, color="gray", is_auth=False):
        self.app.after(0, lambda: (self.status_lbl if is_auth else self.sync_lbl).configure(text=text, text_color=color))

class GphotoComponent(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.fernet = self.init_cipher()
        
        self.tabview = ctk.CTkTabview(self)
        self.tabview._segmented_button.configure(font=("微軟正黑體", 13, "bold"))
        self.tabview.pack(fill="both", expand=True, padx=5, pady=0)
        
        self.tab_a = self.tabview.add("帳號 A")
        self.tab_b = self.tabview.add("帳號 B")

        self.frame_a = GphotoTaskFrame(self.tab_a, "A", app)
        self.frame_a.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.frame_b = GphotoTaskFrame(self.tab_b, "B", app)
        self.frame_b.pack(fill="both", expand=True, padx=10, pady=10)

    def init_cipher(self):
        try:
            k = keyring.get_password(APP_NAME, KEY_ID)
            if not k: k = Fernet.generate_key().decode(); keyring.set_password(APP_NAME, KEY_ID, k)
            return Fernet(k.encode())
        except: return Fernet(Fernet.generate_key())

    def run_tasks(self):
        for f in [self.frame_a, self.frame_b]:
            paths = self.app.db.get_watch_paths(f.tid)
            if paths: self.process_task(f, paths)

    def process_task(self, frame, paths):
        creds = self.auth_task(frame)
        if not creds: return
        service = build('photoslibrary', 'v1', credentials=creds, static_discovery=False)
        scanned, uploaded = 0, 0
        for root in paths:
            if not os.path.exists(root): continue
            with os.scandir(root) as entries:
                for entry in entries:
                    if entry.is_dir() and self.app.running:
                        aid = self.get_aid(service, entry.name)
                        if not aid: continue
                        with os.scandir(entry.path) as files:
                            for f in files:
                                if f.name.lower().endswith(SUPPORTED_FORMATS):
                                    if not self.app.running: break
                                    scanned += 1
                                    st = f.stat()
                                    if scanned % 100 == 0: frame.update_status(f"掃描中 ({scanned})...", "#E76F51")
                                    if not self.app.db.is_uploaded_fast(f.path, st.st_mtime, st.st_size, frame.tid):
                                        uploaded += 1
                                        frame.update_status(f"上傳中 ({uploaded}): {f.name[:10]}", "#2A9D8F")
                                        tk = self.upload_raw(f.path, creds.token)
                                        if tk and self.bind(service, tk, aid):
                                            self.app.db.mark_uploaded_fast(f.path, st.st_mtime, st.st_size, frame.tid)
                                            self.app.log(f"[{frame.name_var.get()}] ✔️ {f.name}")
        if self.app.running: frame.update_status(f"監控中 (總掃描:{scanned})", "#E76F51")

    def auth_task(self, frame):
        tp = os.path.join(get_base_path(), f"token_{frame.tid}.enc")
        creds = None
        if os.path.exists(tp):
            try:
                with open(tp, 'rb') as f: creds = pickle.loads(self.fernet.decrypt(f.read()))
            except: pass
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
            elif frame.creds_path:
                flow = InstalledAppFlow.from_client_secrets_file(frame.creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            else: return None
            with open(tp, 'wb') as f: f.write(self.fernet.encrypt(pickle.dumps(creds)))
        frame.update_status("授權正常", "#2A9D8F", True)
        return creds

    def get_aid(self, s, t):
        try: return s.albums().create(body={'album': {'title': t}}).execute().get('id')
        except: return None

    def upload_raw(self, p, t):
        h = {'Authorization': f'Bearer {t}', 'Content-type': 'application/octet-stream', 'X-Goog-Upload-Protocol': 'raw', 'X-Goog-File-Name': os.path.basename(p).encode('utf-8').decode('latin-1')}
        try:
            with open(p, 'rb') as f:
                r = requests.post(UPLOAD_URL, data=f.read(), headers=h, timeout=120)
                return r.text if r.status_code == 200 else None
        except: return None

    def bind(self, s, t, a):
        try: s.mediaItems().batchCreate(body={'newMediaItems': [{'simpleMediaItem': {'uploadToken': t}}], 'albumId': a}).execute(); return True
        except: return False
