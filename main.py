import os
import sys
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import threading
import pickle
import requests
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Google Photos API 的權限範圍
SCOPES = ['https://www.googleapis.com/auth/photoslibrary']
UPLOAD_URL = 'https://photoslibrary.googleapis.com/v1/uploads'

def get_base_path():
    """取得執行檔或腳本所在的真實資料夾路徑"""
    if getattr(sys, 'frozen', False):
        # 如果是被 PyInstaller 打包後的執行檔
        return os.path.dirname(sys.executable)
    else:
        # 如果是直接執行 Python 腳本
        return os.path.dirname(os.path.abspath(__file__))

class PhotoUploaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Google 相簿自動上傳工具 (打包版)")
        self.root.geometry("600x550")
        
        self.target_folder = ""
        self.credentials_path = ""
        self.creds = None
        self.service = None
        
        # 設定 Token 儲存路徑 (放在執行檔同目錄下)
        self.token_path = os.path.join(get_base_path(), 'token.pickle')

        # --- 介面佈局 ---
        # 1. 選擇 API 憑證
        self.btn_select_creds = tk.Button(root, text="1. 載入 Google API 憑證 (JSON)", command=self.select_credentials, font=("Arial", 11))
        self.btn_select_creds.pack(pady=(15, 5))
        self.lbl_creds = tk.Label(root, text="尚未載入憑證", fg="red")
        self.lbl_creds.pack(pady=5)

        # 2. 選擇資料夾
        self.btn_select_folder = tk.Button(root, text="2. 選擇包含相簿的資料夾", command=self.select_folder, font=("Arial", 11), state=tk.DISABLED)
        self.btn_select_folder.pack(pady=(15, 5))
        self.lbl_path = tk.Label(root, text="尚未選擇資料夾", fg="blue")
        self.lbl_path.pack(pady=5)

        # 3. 執行區塊
        self.btn_start = tk.Button(root, text="3. 開始同步上傳", command=self.start_upload_thread, font=("Arial", 12, "bold"), state=tk.DISABLED)
        self.btn_start.pack(pady=(15, 10))

        # 狀態輸出區塊
        self.log_area = scrolledtext.ScrolledText(root, width=70, height=15, state=tk.DISABLED)
        self.log_area.pack(pady=10)

        # 初始化檢查是否已有 Token
        self.check_existing_token()

    def log(self, message):
        self.log_area.config(state=tk.NORMAL)
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state=tk.DISABLED)
        self.root.update()

    def check_existing_token(self):
        """檢查是否已經有登入過的紀錄"""
        if os.path.exists(self.token_path):
            self.lbl_creds.config(text="偵測到已登入的授權紀錄 (token.pickle)", fg="green")
            self.btn_select_folder.config(state=tk.NORMAL)

    def select_credentials(self):
        """開啟檔案選擇視窗，選擇 credentials.json"""
        file_path = filedialog.askopenfilename(
            title="選擇 Google API 憑證", 
            filetypes=[("JSON Files", "*.json")]
        )
        if file_path:
            self.credentials_path = file_path
            self.lbl_creds.config(text=f"已載入: {os.path.basename(file_path)}", fg="green")
            self.btn_select_folder.config(state=tk.NORMAL)
            self.log("憑證已載入，請選擇要上傳的照片資料夾。")

    def select_folder(self):
        """開啟資料夾選擇視窗"""
        folder_path = filedialog.askdirectory(title="選擇要上傳的根目錄")
        if folder_path:
            self.target_folder = folder_path
            self.lbl_path.config(text=f"已選擇: {self.target_folder}")
            self.btn_start.config(state=tk.NORMAL)
            self.log("資料夾已準備就緒，可以開始上傳。")

    def authenticate(self):
        self.log("正在檢查 Google 授權狀態...")
        
        # 讀取已儲存的 Token
        if os.path.exists(self.token_path):
            with open(self.token_path, 'rb') as token:
                self.creds = pickle.load(token)
        
        # 如果沒有效的憑證，進行登入
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.log("更新過期的憑證...")
                self.creds.refresh(Request())
            else:
                if not self.credentials_path:
                    messagebox.showerror("錯誤", "請先點擊「載入 Google API 憑證」選擇你的 JSON 檔案！")
                    return False
                self.log("需要瀏覽器授權，請注意彈出的網頁視窗。")
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                self.creds = flow.run_local_server(port=0)
            
            # 將成功登入的 Token 存下來
            with open(self.token_path, 'wb') as token:
                pickle.dump(self.creds, token)

        self.service = build('photoslibrary', 'v1', credentials=self.creds, static_discovery=False)
        self.log("Google 帳號授權成功！")
        return True

    # ---------- (以下 API 建立相簿與上傳邏輯皆與先前相同，未做變動) ----------
    def create_album(self, album_title):
        try:
            album_body = {'album': {'title': album_title}}
            response = self.service.albums().create(body=album_body).execute()
            return response.get('id')
        except Exception as e:
            self.log(f"建立相簿 [{album_title}] 失敗: {str(e)}")
            return None

    def upload_photo(self, file_path):
        try:
            headers = {
                'Authorization': 'Bearer ' + self.creds.token,
                'Content-type': 'application/octet-stream',
                'X-Goog-Upload-Protocol': 'raw',
                'X-Goog-File-Name': os.path.basename(file_path).encode('utf-8').decode('latin-1')
            }
            with open(file_path, 'rb') as item_file:
                item_bytes = item_file.read()
            
            response = requests.post(UPLOAD_URL, data=item_bytes, headers=headers)
            return response.text
        except Exception as e:
            self.log(f"檔案上傳失敗 [{file_path}]: {str(e)}")
            return None

    def add_to_album(self, upload_token, album_id, file_name):
        try:
            new_item = {
                'newMediaItems': [{
                    'description': file_name,
                    'simpleMediaItem': {'uploadToken': upload_token}
                }],
                'albumId': album_id
            }
            self.service.mediaItems().batchCreate(body=new_item).execute()
        except Exception as e:
            self.log(f"加入相簿失敗 [{file_name}]: {str(e)}")

    def start_upload_thread(self):
        self.btn_select_creds.config(state=tk.DISABLED)
        self.btn_select_folder.config(state=tk.DISABLED)
        self.btn_start.config(state=tk.DISABLED)
        thread = threading.Thread(target=self.process_folders)
        thread.daemon = True
        thread.start()

    def process_folders(self):
        if not self.authenticate():
            self.btn_select_creds.config(state=tk.NORMAL)
            self.btn_select_folder.config(state=tk.NORMAL)
            return

        self.log(f"\n--- 開始掃描: {self.target_folder} ---")
        
        for item in os.listdir(self.target_folder):
            folder_path = os.path.join(self.target_folder, item)
            if os.path.isdir(folder_path):
                self.log(f"\n📁 發現資料夾: {item}，準備建立相簿...")
                album_id = self.create_album(item)
                if not album_id: continue
                
                supported_formats = ('.jpg', '.jpeg', '.png', '.heic', '.webp')
                for file_name in os.listdir(folder_path):
                    if file_name.lower().endswith(supported_formats):
                        file_path = os.path.join(folder_path, file_name)
                        self.log(f"  └ 正在上傳: {file_name} ...")
                        upload_token = self.upload_photo(file_path)
                        if upload_token:
                            self.add_to_album(upload_token, album_id, file_name)
                            self.log(f"    ✔️ 上傳完成")

        self.log("\n🎉 所有資料夾處理完畢！")
        self.btn_select_creds.config(state=tk.NORMAL)
        self.btn_select_folder.config(state=tk.NORMAL)
        self.btn_start.config(state=tk.NORMAL)

if __name__ == "__main__":
    root = tk.Tk()
    app = PhotoUploaderApp(root)
    root.mainloop()
