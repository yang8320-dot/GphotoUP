import os
import sys
import time
import subprocess
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk

def get_rclone_path():
    # 🚀 關鍵修正：支援 PyInstaller 6+ 的 _internal 目錄
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
        internal = os.path.join(base, "_internal", "rclone.exe")
        if os.path.exists(internal): return internal
        return os.path.join(base, "rclone.exe")
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rclone.exe")

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
        
        ctk.CTkLabel(self.top, text="頻寬限制 (如 500K 或 10M):").grid(row=3, column=0, padx=10, pady=5)
        self.bw_entry = ctk.CTkEntry(self.top, placeholder_text="不限速請留空")
        self.bw_entry.grid(row=3, column=1, padx=10, pady=5, sticky="we")
        
        # 🎨 高對比深藍色按鈕
        ctk.CTkButton(self.top, text="加入同步清單", fg_color="#1F6AA5", text_color="#FFFFFF", command=self.add_sync).grid(row=4, column=0, columnspan=2, pady=15)

        self.scroll = ctk.CTkScrollableFrame(self, height=250, corner_radius=15)
        self.scroll.pack(fill="both", expand=True, padx=20, pady=10)
        self.render_tasks()

    def sel_src(self): p = filedialog.askdirectory(); self.src_var.set(p if p else "未選擇來源")
    def sel_tgt(self): p = filedialog.askdirectory(); self.tgt_var.set(p if p else "未選擇目標")

    def add_sync(self):
        s, t, b = self.src_var.get(), self.tgt_var.get(), self.bw_entry.get()
        if "未選擇" in s or "未選擇" in t: return
        self.app.db.add_sync_task(s, t, b.strip())
        self.render_tasks()

    def render_tasks(self):
        for w in self.scroll.winfo_children(): w.destroy()
        for tid, s, t, b in self.app.db.get_sync_tasks():
            f = ctk.CTkFrame(self.scroll)
            f.pack(fill="x", pady=2, padx=5)
            ctk.CTkLabel(f, text=f"從: {os.path.basename(s)} ⮕ 到: {os.path.basename(t)} (限速: {b if b else '無'})", font=("Arial", 11)).pack(side="left", padx=10)
            ctk.CTkButton(f, text="刪除", width=50, fg_color="#FF3B30", command=lambda x=tid: self.del_task(x)).pack(side="right", padx=5)

    def del_task(self, tid): self.app.db.delete_sync_task(tid); self.render_tasks()

    def run_tasks(self):
        tasks = self.app.db.get_sync_tasks()
        for tid, src, tgt, bw in tasks:
            if not self.app.running: break
            self.execute_rclone(src, tgt, bw)

    def execute_rclone(self, src, tgt, bw):
        r_path = get_rclone_path()
        if not os.path.exists(r_path):
            self.app.log("❌ 找不到 rclone.exe 引擎！")
            return

        cmd = [r_path, "sync", src, tgt, "--ignore-existing", "--progress"]
        if bw: cmd.extend(["--bwlimit", bw])
        
        self.app.log(f"🔄 [Sync] 同步開始: {os.path.basename(src)}")
        try:
            # 🚀 關鍵修正：解決 cp950 編碼錯誤
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                     text=True, encoding='utf-8', errors='replace',
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            
            l_t = time.time()
            for line in process.stdout:
                if not self.app.running: process.terminate(); break
                if "Transferred:" in line and time.time() - l_t > 3:
                    self.app.log(f"[進度] {line.strip().replace('Transferred:', '')}")
                    l_t = time.time()
            process.wait()
            if self.app.running: self.app.log(f"✅ [Sync] {os.path.basename(src)} 完成")
        except Exception as e:
            self.app.log(f"❌ 同步失敗: {e}")
