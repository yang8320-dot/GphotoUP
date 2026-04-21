# --- START OF FILE folder_sync.py ---
import os
import sys
import time
import subprocess
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk

def get_rclone_path():
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
        
        # 🎨 版面大幅修改：改為 Tabview 分頁顯示
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=5, pady=0)
        
        self.tab_new = self.tabview.add("新任務設定")
        self.tab_list = self.tabview.add("任務清單")

        # ----------------------------------------
        # 分頁 1：新任務設定區塊
        # ----------------------------------------
        self.top = ctk.CTkFrame(self.tab_new, corner_radius=15)
        self.top.pack(fill="both", expand=True, padx=15, pady=15)
        
        self.top.grid_columnconfigure(1, weight=1) # 讓輸入框與文字吃滿空間
        
        ctk.CTkLabel(self.top, text="新同步任務設定", font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(15, 10))
        
        self.src_var = tk.StringVar(value="未選擇來源")
        ctk.CTkButton(self.top, text="選擇來源", width=90, command=self.sel_src).grid(row=1, column=0, padx=15, pady=10)
        ctk.CTkLabel(self.top, textvariable=self.src_var, justify="left", wraplength=300).grid(row=1, column=1, sticky="w", padx=(0, 15))
        
        self.tgt_var = tk.StringVar(value="未選擇目標")
        ctk.CTkButton(self.top, text="選擇目標", width=90, command=self.sel_tgt).grid(row=2, column=0, padx=15, pady=10)
        ctk.CTkLabel(self.top, textvariable=self.tgt_var, justify="left", wraplength=300).grid(row=2, column=1, sticky="w", padx=(0, 15))
        
        ctk.CTkLabel(self.top, text="頻寬限制\n(留空不限速):", justify="right").grid(row=3, column=0, padx=15, pady=10)
        self.bw_entry = ctk.CTkEntry(self.top, placeholder_text="如 500K 或 10M", width=150)
        self.bw_entry.grid(row=3, column=1, padx=(0, 15), pady=10, sticky="w")
        
        ctk.CTkButton(self.top, text="加入同步清單", fg_color="#1F6AA5", text_color="#FFFFFF", command=self.add_sync).grid(row=4, column=0, columnspan=2, pady=(20, 10))

        # ----------------------------------------
        # 分頁 2：任務清單區塊
        # ----------------------------------------
        self.list_frame = ctk.CTkFrame(self.tab_list, corner_radius=15)
        self.list_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(self.list_frame, text="執行中 / 待命同步任務", font=("Arial", 16, "bold")).pack(pady=(15, 5))
        
        self.scroll = ctk.CTkScrollableFrame(self.list_frame, corner_radius=10)
        self.scroll.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.render_tasks()

    def sel_src(self): 
        p = filedialog.askdirectory(); self.src_var.set(p if p else "未選擇來源")
    def sel_tgt(self): 
        p = filedialog.askdirectory(); self.tgt_var.set(p if p else "未選擇目標")

    def add_sync(self):
        s, t, b = self.src_var.get(), self.tgt_var.get(), self.bw_entry.get()
        if "未選擇" in s or "未選擇" in t: return
        self.app.db.add_sync_task(s, t, b.strip())
        self.render_tasks()
        
        # 💡 新增功能：加完清單後自動跳轉到「任務清單」分頁給使用者看
        self.tabview.set("任務清單")

    def render_tasks(self):
        for w in self.scroll.winfo_children(): w.destroy()
        for tid, s, t, b in self.app.db.get_sync_tasks():
            f = ctk.CTkFrame(self.scroll)
            f.pack(fill="x", pady=5, padx=5)
            # 因為現在只有單欄，可以顯示稍微長一點的路徑
            ctk.CTkLabel(f, text=f"從: {s}\n到: {t}\n限速: {b if b else '無'}", font=("Arial", 11), justify="left", wraplength=350).pack(side="left", padx=10, pady=5)
            ctk.CTkButton(f, text="刪除", width=50, fg_color="#FF3B30", command=lambda x=tid: self.del_task(x)).pack(side="right", padx=10)

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
