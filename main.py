import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import pickle
import requests
import keyring
from cryptography.fernet import Fernet
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# 導入現代化 UI 框架
import customtkinter as ctk

# --- 解決 Windows 螢幕縮放導致的字體模糊問題 (DPI Awareness) ---
try:
    from ctypes import windll
    # 告訴 Windows 這個程式支援高 DPI，不要強制點陣放大
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# 設定 customtkinter 的全域主題風格 (類似 iOS / macOS)
ctk.set_appearance_mode("System")  # 跟隨系統的深色/淺色模式
ctk.set_default_color_theme("blue") # 主要按鈕顏色

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
        self.root.title("Google 相簿自動上傳器")
        self.root.geometry("650x600")
        
        self.target_folder = ""
        self.credentials_path = ""
        self.creds = None
        self.service = None
        
        self.encrypted_token_path = os.path.join(get_base_path(), 'token.enc')
        self.fernet = self.init_cipher()

        # --- 建立現代化 (iOS 風格) 的 GUI 介面 ---
        # 標題
        self.title_label = ctk.CTkLabel(root, text="Google 相簿同步工具", font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.pack(pady=(20, 10))

        # 區塊 1: 憑證載入
        self.frame_creds = ctk.CTkFrame(root, corner_radius=15, fg_color="transparent")
        self.frame_creds.pack(pady=10, fill="x", padx=40)
        
        self.btn_select_creds = ctk.CTkButton(self.frame_creds, text="1. 載入 Google API 憑證 (JSON)", 
                                              command=self.select_credentials, font=ctk.CTkFont(size=14),
                                              corner_radius=8, height=40)
        self.btn_select_creds.pack(pady=5)
        self.lbl_creds = ctk.CTkLabel(self.frame_creds, text="尚未載入憑證", text_color="#FF3B30") # iOS 紅色
        self.lbl_creds.pack()

        # 區塊 2: 資料夾選擇
        self.frame_folder = ctk.CTkFrame(root, corner_radius=15, fg_color="transparent")
        self.frame_folder.pack(pady=10, fill="x", padx=40)

        self.btn_select_folder = ctk.CTkButton(self.frame_folder, text="2. 選擇相簿資料夾", 
                                               command=self.select_folder, font=ctk.CTkFont(size=14),
                                               corner_radius=8, height=40, state="disabled", fg_color="#5ac8fa") # iOS 淺藍
        self.btn_select_folder.pack(pady=5)
        self.lbl_path = ctk.CTkLabel(self.frame_folder, text="尚未選擇資料夾", text_color="gray")
        self.lbl_path.pack()

        # 區塊 3: 執行按鈕
        self.btn_start = ctk.CTkButton(root, text="開始同步上傳", command=self.start_upload_thread, 
                                       font=ctk.CTkFont(size=16, weight="bold"), corner_radius=20, 
                                       height=50, state="disabled", fg_color="#34c759", hover_color="#32b353") # iOS 綠色
        self.btn_start.pack(pady=(20, 10))

        # 區塊 4: 日誌輸出視窗 (帶圓角與平滑滾動)
        self.log_area = ctk.CTkTextbox(root, width=550, height=200, corner_radius=10, 
                                       font=ctk.CTkFont(family="Consolas", size=13))
        self.log_area.pack(pady=10)
        self.log_area.configure(state="disabled")

        self.check_existing_session()

    def init_cipher(self):
        key = keyring.get_password(APP_NAME, KEY_ID)
        if not key:
            key = Fernet.generate_key().decode()
            keyring.set_password(APP_NAME, KEY_ID, key)
        return Fernet(key.encode())

    def log(self, message):
        self.root.after(0, self._update_log, message)

    def _update_log(self, message):
        self.log_area.configure(state="normal")
        self.log_area.insert("end", message + "\n")
        self.log_area.see("end")
        self.log_area.configure(state="disabled")

    def check_existing_session(self):
        if os.path.exists(self.encrypted_token_path):
            self.lbl_creds.configure(text="偵測到加密的授權紀錄 (token.enc)", text_color="#34c759")
            self.btn_select_folder.configure(state="normal", fg_color="#007AFF")

    def select_credentials(self):
        path = filedialog.askopenfilename(title="選擇 Google API 憑證", filetypes=[("JSON Files", "*.json")])
        if path:
            self.credentials_path = path
            self.lbl_creds.configure(text=f"已載入: {os.path.basename(path)}", text_color="#34c759")
            self.btn_select_folder.configure(state="normal", fg_color="#007AFF")

    def select_folder(self):
        path = filedialog.askdirectory(title="選擇要上傳的根目錄")
        if path:
            self.target_folder = path
            self.lbl_path.configure(text=f"已選擇: {path}")
            self.btn_start.configure(state="normal")

    def save_creds_encrypted(self, creds):
        data = pickle.dumps(creds)
        encrypted_data = self.fernet.encrypt(data)
        with open(self.encrypted_token_path, 'wb') as f:
            f.write(encrypted_data)

    def load_creds_encrypted(self):
        try:
            with open(self.encrypted_token_path, 'rb') as f:
                encrypted_data = f.read()
            decrypted_data = self.fernet.decrypt(encrypted_data)
            return pickle.loads(decrypted_data)
        except Exception as e:
            self.log(f"解密授權檔失敗: {e}")
            return None

    def authenticate(self):
        self.log("正在驗證 Google 帳號權限...")
        if os.path.exists(self.encrypted_token_path):
            self.creds = self.load_creds_encrypted()
        
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.log("更新過期的授權...")
                self.creds.refresh(Request())
            else:
                if not self.credentials_path:
                    messagebox.showerror("錯誤", "第一次登入需要載入 API JSON 憑證！")
                    return False
                self.log("需要瀏覽器授權，請注意彈出的網頁視窗...")
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                self.creds = flow.run_local_server(port=0)
            
            self.save_creds_encrypted(self.creds)
            self.log("授權已成功加密並儲存。")

        self.service = build('photoslibrary', 'v1', credentials=self.creds, static_discovery=False)
        return True

    def create_album(self, title):
        try:
            return self.service.albums().create(body={'album': {'title': title}}).execute().get('id')
        except Exception as e:
            self.log(f"❌ 建立相簿失敗 [{title}]: {e}")
            return None

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
        except Exception as e:
            self.log(f"❌ 上傳失敗 [{os.path.basename(path)}]: {e}")
            return None

    def add_to_album(self, token, album_id, name):
        try:
            body = {'newMediaItems': [{'description': name, 'simpleMediaItem': {'uploadToken': token}}], 'albumId': album_id}
            self.service.mediaItems().batchCreate(body=body).execute()
        except Exception as e:
            self.log(f"❌ 加入相簿失敗 [{name}]: {e}")

    def start_upload_thread(self):
        self.btn_select_creds.configure(state="disabled")
        self.btn_select_folder.configure(state="disabled")
        self.btn_start.configure(state="disabled")
        threading.Thread(target=self.process, daemon=True).start()

    def process(self):
        if not self.authenticate(): 
            self.btn_select_creds.configure(state="normal")
            self.btn_select_folder.configure(state="normal")
            return
        
        self.log(f"\n--- 開始掃描: {self.target_folder} ---")
        
        for item in os.listdir(self.target_folder):
            path = os.path.join(self.target_folder, item)
            if os.path.isdir(path):
                self.log(f"\n📁 準備建立相簿: {item}")
                aid = self.create_album(item)
                if not aid: continue
                
                supported_formats = ('.jpg', '.jpeg', '.png', '.heic', '.webp')
                for f in os.listdir(path):
                    if f.lower().endswith(supported_formats):
                        self.log(f"  └ 上傳: {f} ...")
                        utoken = self.upload_photo(os.path.join(path, f))
                        if utoken: 
                            self.add_to_album(utoken, aid, f)
                            self.log(f"    ✔️ 完成")
        
        self.log("\n🎉 所有資料夾處理完畢！")
        self.btn_select_creds.configure(state="normal")
        self.btn_select_folder.configure(state="normal")
        self.btn_start.configure(state="normal")

if __name__ == "__main__":
    # 使用 customtkinter 的主視窗
    root = ctk.CTk()
    app = PhotoUploaderApp(root)
    root.mainloop()
