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
        
        self.tabview = ctk.CTkTabview(self)
        self.tabview._segmented_button.configure(font=("微軟正黑體", 13, "bold"))
        self.tabview.pack(fill="both", expand=True, padx=5, pady=0)
        
        self.tab_new = self.tabview.add("新任務設定")
        self.tab_list = self.tabview.add("任務清單")

        # ----------------------------------------
        # 分頁 1：新任務設定區塊
        # ----------------------------------------
        self.top = ctk.CTkFrame(self.tab_new, corner_radius=15, fg_color="transparent")
        self.top.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.top.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.top, text="新同步任務設定", font=("微軟正黑體", 18, "bold"), text_color=("#111111", "#FFFFFF")).grid(row=0, column=0, columnspan=2, pady=(15, 10))
        
        self.src_var = tk.StringVar(value="未選擇來源")
        ctk.CTkButton(self.top, text="選擇來源", font=("微軟正黑體", 13, "bold"), width=100, height=35, command=self.sel_src).grid(row=1, column=0, padx=15, pady=10)
        ctk.CTkLabel(self.top, textvariable=self.src_var, font=("微軟正黑體", 13), text_color=("#333333", "#CCCCCC"), justify="left", wraplength=300).grid(row=1, column=1, sticky="w", padx=(0, 15))
        
        self.tgt_var = tk.StringVar(value="未選擇目標")
        ctk.CTkButton(self.top, text="選擇目標", font=("微軟正黑體", 13, "bold"), width=100, height=35, command=self.sel_tgt).grid(row=2, column=0, padx=15, pady=10)
        ctk.CTkLabel(self.top, textvariable=self.tgt_var, font=("微軟正黑體", 13), text_color=("#333333", "#CCCCCC"), justify="left", wraplength=300).grid(row=2, column=1, sticky="w", padx=(0, 15))
        
        ctk.CTkLabel(self.top, text="頻寬限制\n(留空不限速):", font=("微軟正黑體", 13, "bold"), text_color=("#333333", "#CCCCCC"), justify="right").grid(row=3, column=0, padx=15, pady=10)
        self.bw_entry = ctk.CTkEntry(self.top, placeholder_text="如 500K 或 10M", font=("微軟正黑體", 13), width=150)
        self.bw_entry.grid(row=3, column=1, padx=(0, 15), pady=10, sticky="w")
        
        ctk.CTkButton(self.top, text="加入同步清單", font=("微軟正黑體", 14, "bold"), height=40, fg_color="#2A9D8F", text_color="#FFFFFF", command=self.add_sync).grid(row=4, column=0, columnspan=2, pady=(25, 10))

        # ----------------------------------------
        # 分頁 2：任務清單區塊
        # ----------------------------------------
        self.list_frame = ctk.CTkFrame(self.tab_list, corner_radius=15, fg_color="transparent")
        self.list_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        ctk.CTkLabel(self.list_frame, text="執行中 / 待命同步任務", font=("微軟正黑體", 16, "bold"), text_color=("#111111", "#FFFFFF")).pack(pady=(10, 5))
        
        self.scroll = ctk.CTkScrollableFrame(self.list_frame, corner_radius=10, fg_color=("#F0F0F0", "#212121"))
        self.scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
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
        self.tabview.set("任務清單")

    def render_tasks(self):
        for w in self.scroll.winfo_children(): w.destroy()
        for tid, s, t, b in self.app.db.get_sync_tasks():
            # 🌟 獨立任務卡片，加上白底(淺色)/深灰底(深色)，產生立體感
            f = ctk.CTkFrame(self.scroll, fg_color=("#FFFFFF", "#2B2B2B"), corner_radius=8, border_width=1, border_color="#CCCCCC")
            f.pack(fill="x", pady=5, padx=5)
            
            info_text = f"從: {s}\n到: {t}\n限速: {b if b else '無'}"
            ctk.CTkLabel(f, text=info_text, font=("微軟正黑體", 12, "bold"), text_color=("#111111", "#EEEEEE"), justify="left", wraplength=330).pack(side="left", padx=15, pady=10)
            ctk.CTkButton(f, text="刪除", font=("微軟正黑體", 12, "bold"), width=60, height=30, fg_color="#E63946", command=lambda x=tid: self.del_task(x)).pack(side="right", padx=15)

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
