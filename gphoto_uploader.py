import os
import pickle
import time
import requests
import sqlite3
from tkinter import filedialog, tk
import customtkinter as ctk
import keyring
from cryptography.fernet import Fernet
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/photoslibrary']
UPLOAD_URL = 'https://photoslibrary.googleapis.com/v1/uploads'
SUPPORTED_FORMATS = ('.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif', '.mp4', '.mov', '.avi')

def get_base_path():
    return os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))

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

    def get_watch_paths(self, tid):
        with sqlite3.connect(self.db_path) as conn:
            return [row[0] for row in conn.execute("SELECT path FROM watch_paths WHERE task_id=?", (tid,)).fetchall()]

    def is_uploaded(self, fp, tid):
        if not os.path.exists(fp): return True
        s = os.stat(fp)
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT 1 FROM uploads WHERE file_path=? AND mtime=? AND size=? AND task_id=?", (fp, s.st_mtime, s.st_size, tid)).fetchone() is not None

    def mark_uploaded(self, fp, tid):
        s = os.stat(fp)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO uploads VALUES (?, ?, ?, ?)", (fp, s.st_mtime, s.st_size, tid))

class GphotoComponent(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure((0, 1), weight=1)
        
        self.frame_a = self.create_task_ui("A")
        self.frame_a.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.frame_b = self.create_task_ui("B")
        self.frame_b.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

    def create_task_ui(self, tid):
        f = ctk.CTkFrame(self, corner_radius=15)
        # UI 略，這裡放置原本的清單、新增刪除按鈕邏輯
        # 實務上請參考前幾次對 TaskManagerFrame 的詳細實作
        return f

    def run_tasks(self):
        # 執行 A 和 B 的輪詢上傳邏輯
        pass
