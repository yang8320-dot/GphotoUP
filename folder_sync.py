import os
import sys
import time
import subprocess
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk

def get_rclone_path():
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    return os.path.join(base, 'rclone.exe')

class SyncComponent(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        
        self.top = ctk.CTkFrame(self, corner_radius=15)
        self.top.pack(pady=10, padx=20, fill="x")
        
        ctk.CTkLabel(self.top, text="新同步任務設定", font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=10)
        
        self.src_var = tk.StringVar(value="未選擇來源")
        ctk.CTkButton(self.top, text="選擇來源資料夾", command=self.sel_src).grid(row=1, column=0, padx=10, pady=5)
        ctk.CTkLabel(self.top, textvariable=self.src_var).grid(row=1, column=1, sticky="w")
        
        self.tgt_var = tk.StringVar(value="未選擇目標")
        ctk.CTkButton(self.top, text="選擇目標資料夾", command=self.sel_tgt).grid(row=2, column=0, padx=10, pady=5)
        ctk.CTkLabel(self.top, textvariable=self.tgt_var).grid(row=2, column=1, sticky="w")
        
        ctk.CTkLabel(self.top, text="頻寬限制 (如 500K 或 10M，不限留空):").grid(row=3, column=0, padx=10, pady=5)
        self.bw_entry = ctk.CTkEntry(self.top, placeholder_text="不限速請留空")
        self.bw_entry.grid(row=3, column=1, padx=10, pady=5, sticky="we")
        
        ctk.CTkButton(self.top, text="加入同步清單", fg_color="#34c759", command=self.add_sync).grid(row=4, column=0, columnspan=2, pady=15)

        self.list_frame = ctk.CTkFrame(self, corner_radius=15)
        self.list_frame.pack(pady=10, padx=20, fill="both", expand=True)
        ctk.CTkLabel(self.list_frame, text="執行中/待命同步任務", font=("Arial", 14)).pack(pady=5)
        
        self.scroll = ctk.CTkScrollableFrame(self.list_frame, height=200)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=10)
        self.render_tasks()

    def sel_src(self): 
        p = filedialog.askdirectory(); self.src_var.set(p if p else "未選擇來源")
    
    def sel_tgt(self): 
        p = filedialog.askdirectory(); self.tgt_var.set(p if p else "未選擇目標")

    def add_sync(self):
        s, t, b = self.src_var.get(), self.tgt_var.get(), self.bw_entry.get()
        if "未選擇" in s or "未選擇" in t: return
        self.app.db.add_sync_task(s, t, b)
        self.render_tasks()

    def render_tasks(self):
        for widget in self.scroll.winfo_children(): widget.destroy()
        for tid, s, t, b in self.app.db.get_sync_tasks():
            f = ctk.CTkFrame(self.scroll)
            f.pack(fill="x", pady=2, padx=5)
            ctk.CTkLabel(f, text=f"從: {os.path.basename(s)} ⮕ 到: {os.path.basename(t)} (限速: {b if b else '無'})", font=("Arial", 11)).pack(side="left", padx=10)
            ctk.CTkButton(f, text="刪除", width=50, fg_color="#FF3B30", command=lambda x=tid: self.del_task(x)).pack(side="right", padx=5)

    def del_task(self, tid): 
        self.app.db.delete_sync_task(tid); self.render_tasks()

    def run_tasks(self):
        tasks = self.app.db.get_sync_tasks()
        for tid, src, tgt, bw in tasks:
            if not self.app.running: break
            self.execute_rclone(src, tgt, bw)

    # 🚀 升級：使用 Popen 攔截 Rclone 即時進度
    def execute_rclone(self, src, tgt, bw):
        rclone_exe = get_rclone_path()
        cmd = [rclone_exe, "sync", src, tgt, "--ignore-existing", "--progress"]
        if bw: cmd.extend(["--bwlimit", bw])
        
        self.app.log(f"🔄 [Sync] 開始同步: {os.path.basename(src)}")
        try:
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            last_log_time = time.time()
            for line in process.stdout:
                if not self.app.running:
                    process.terminate() # 如果使用者按停止，強制關閉 rclone
                    break
                
                # Rclone 的進度關鍵字是 "Transferred:"
                if "Transferred:" in line:
                    current_time = time.time()
                    # 每 3 秒更新一次日誌，避免文字狂洗版導致 UI 卡頓
                    if current_time - last_log_time > 3:
                        clean_line = line.strip().replace("Transferred:", "[進度]")
                        self.app.log(clean_line)
                        last_log_time = current_time

            process.wait() # 等待進程完全結束
            
            if self.app.running:
                self.app.log(f"✅ [Sync] {os.path.basename(src)} 同步完成")
            else:
                self.app.log(f"🛑 [Sync] {os.path.basename(src)} 同步已中斷")
                
        except Exception as e:
            self.app.log(f"❌ Rclone 錯誤: {e}")
