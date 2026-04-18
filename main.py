import os
import sys
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import threading
import pickle
import requests
import keyring # 儲存金鑰至系統憑證
from cryptography.fernet import Fernet # 加密邏輯
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Google Photos API 設定
SCOPES = ['https://www.googleapis.com/auth/photoslibrary']
UPLOAD_URL = 'https://photoslibrary.googleapis.com/v1/uploads'
APP_NAME = "GooglePhotosUploader_V1"
KEY_ID = "EncryptionKey"

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

class PhotoUploaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Google 相簿自動上傳器 (加密安全版)")
        self.root.geometry("600x550")
        
        self.target_folder = ""
        self.credentials_path = ""
        self.creds = None
        self.service = None
        
        # 加密後的 Token 檔案路徑
        self.encrypted_token_path = os.path.join(get_base_path(), 'token.enc')
        
        # 初始化加密金鑰
        self.fernet = self.init_cipher()

        # --- GUI 介面 ---
        self.btn_select_creds = tk.Button(root, text="1. 載入 Google API 憑證 (JSON)", command=self.select_credentials)
        self.btn_select_creds.pack(pady=10)
        self.lbl_creds = tk.Label(root, text="尚未載入憑證", fg="red")
        self.lbl_creds.pack()

        self.btn_select_folder = tk.Button(root, text="2. 選擇照片資料夾", command=self.select_folder, state=tk.DISABLED)
        self.btn_select_folder.pack(pady=10)
        self.lbl_path = tk.Label(root, text="尚未選擇資料夾", fg="blue")
        self.lbl_path.pack()

        self.btn_start = tk.Button(root, text="3. 開始同步上傳", command=self.start_upload_thread, font=("Arial", 12, "bold"), state=tk.DISABLED)
        self.btn_start.pack(pady=20)

        self.log_area = scrolledtext.ScrolledText(root, width=70, height=15, state=tk.DISABLED)
        self.log_area.pack(pady=10)

        self.check_existing_session()

    def init_cipher(self):
        """從系統憑證管理員取得金鑰，若無則產生"""
        key = keyring.get_password(APP_NAME, KEY_ID)
        if not key:
            # 產生新金鑰並存入系統
            key = Fernet.generate_key().decode()
            keyring.set_password(APP_NAME, KEY_ID, key)
        return Fernet(key.encode())

    def log(self, message):
        self.log_area.config(state=tk.NORMAL)
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state=tk.DISABLED)
        self.root.update()

    def check_existing_session(self):
        if os.path.exists(self.encrypted_token_path):
            self.lbl_creds.config(text="偵測到加密授權紀錄", fg="green")
            self.btn_select_folder.config(state=tk.NORMAL)

    def select_credentials(self):
        path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if path:
            self.credentials_path = path
            self.lbl_creds.config(text=f"已載入: {os.path.basename(path)}", fg="green")
            self.btn_select_folder.config(state=tk.NORMAL)

    def select_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.target_folder = path
            self.lbl_path.config(text=f"已選擇: {path}")
            self.btn_start.config(state=tk.NORMAL)

    def save_creds_encrypted(self, creds):
        """加密並儲存 Token"""
        data = pickle.dumps(creds)
        encrypted_data = self.fernet.encrypt(data)
        with open(self.encrypted_token_path, 'wb') as f:
            f.write(encrypted_data)

    def load_creds_encrypted(self):
        """解密並讀取 Token"""
        try:
            with open(self.encrypted_token_path, 'rb') as f:
                encrypted_data = f.read()
            decrypted_data = self.fernet.decrypt(encrypted_data)
            return pickle.loads(decrypted_data)
        except Exception:
            return None

    def authenticate(self):
        self.log("正在解密並驗證權限...")
        if os.path.exists(self.encrypted_token_path):
            self.creds = self.load_creds_encrypted()
        
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.log("更新過期的授權...")
                self.creds.refresh(Request())
            else:
                if not self.credentials_path:
                    messagebox.showerror("錯誤", "需要 API JSON 憑證進行第一次登入")
                    return False
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                self.creds = flow.run_local_server(port=0)
            
            self.save_creds_encrypted(self.creds)
            self.log("授權已加密儲存。")

        self.service = build('photoslibrary', 'v1', credentials=self.creds, static_discovery=False)
        return True

    # --- 上傳邏輯 (同前) ---
    def create_album(self, title):
        try:
            return self.service.albums().create(body={'album': {'title': title}}).execute().get('id')
        except: return None

    def upload_photo(self, path):
        try:
            headers = {
                'Authorization': f'Bearer {self.creds.token}',
                'Content-type': 'application/octet-stream',
                'X-Goog-Upload-Protocol': 'raw',
                'X-Goog-File-Name': os.path.basename(path).encode('utf-8').decode('latin-1')
            }
            with open(path, 'rb') as f:
                return requests.post(UPLOAD_URL, data=f.read(), headers=headers).text
        except: return None

    def add_to_album(self, token, album_id, name):
        body = {'newMediaItems': [{'description': name, 'simpleMediaItem': {'uploadToken': token}}], 'albumId': album_id}
        self.service.mediaItems().batchCreate(body=body).execute()

    def start_upload_thread(self):
        self.btn_start.config(state=tk.DISABLED)
        threading.Thread(target=self.process, daemon=True).start()

    def process(self):
        if not self.authenticate(): 
            self.btn_start.config(state=tk.NORMAL)
            return
        
        for item in os.listdir(self.target_folder):
            path = os.path.join(self.target_folder, item)
            if os.path.isdir(path):
                self.log(f"📁 建立相簿: {item}")
                aid = self.create_album(item)
                if not aid: continue
                for f in os.listdir(path):
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.heic')):
                        self.log(f"  └ 上傳: {f}")
                        utoken = self.upload_photo(os.path.join(path, f))
                        if utoken: self.add_to_album(utoken, aid, f)
        
        self.log("\n✅ 同步完成！")
        self.btn_start.config(state=tk.NORMAL)

if __name__ == "__main__":
    root = tk.Tk()
    app = PhotoUploaderApp(root)
    root.mainloop()
