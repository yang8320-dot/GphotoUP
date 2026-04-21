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
        
        ctk.CTkLabel(self.top, text="新同步任務設定", font=("微軟正黑體", 18, "bold"), text_color=("#111111", "#FFFFFF")).grid(row=0, column=0, columnspan=2, pady=(10, 10))
        
        self.src_var = tk.StringVar(value="未選擇來源")
        ctk.CTkButton(self.top, text="選擇來源", font=("微軟正黑體", 13, "bold"), width=100, height=35, command=self.sel_src).grid(row=1, column=0, padx=15, pady=10)
        ctk.CTkLabel(self.top, textvariable=self.src_var, font=("微軟正黑體", 13), text_color=("#333333", "#CCCCCC"), justify="left", wraplength=300).grid(row=1, column=1, sticky="w", padx=(0, 15))
        
        self.tgt_var = tk.StringVar(value="未選擇目標")
        ctk.CTkButton(self.top, text="選擇目標", font=("微軟正黑體", 13, "bold"), width=100, height=35, command=self.sel_tgt).grid(row=2, column=0, padx=15, pady=10)
        ctk.CTkLabel(self.top, textvariable=self.tgt_var, font=("微軟正黑體", 13), text_color=("#333333", "#CCCCCC"), justify="left", wraplength=300).grid(row=2, column=1, sticky="w", padx=(0, 15))
        
        # 🚀 新增功能：同步模式選擇
        ctk.CTkLabel(self.top, text="同步模式:", font=("微軟正黑體", 13, "bold"), text_color=("#333333", "#CCCCCC"), justify="right").grid(row=3, column=0, padx=15, pady=10)
        self.mode_var = ctk.StringVar(value="單向同步")
        self.mode_seg = ctk.CTkSegmentedButton(self.top, values=["單向同步", "雙向同步"], variable=self.mode_var, font=("微軟正黑體", 12, "bold"))
        self.mode_seg.grid(row=3, column=1, padx=(0, 15), pady=10, sticky="w")
        
        ctk.CTkLabel(self.top, text="頻寬限制\n(留空不限速):", font=("微軟正黑體", 13, "bold"), text_color=("#333333", "#CCCCCC"), justify="right").grid(row=4, column=0, padx=15, pady=10)
        self.bw_entry = ctk.CTkEntry(self.top, placeholder_text="如 500K 或 10M", font=("微軟正黑體", 13), width=150)
        self.bw_entry.grid(row=4, column=1, padx=(0, 15), pady=10, sticky="w")
        
        ctk.CTkButton(self.top, text="加入同步清單", font=("微軟正黑體", 14, "bold"), height=40, fg_color="#2A9D8F", text_color="#FFFFFF", command=self.add_sync).grid(row=5, column=0, columnspan=2, pady=(20, 5))

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
        mode = self.mode_var.get()
        if "未選擇" in s or "未選擇" in t: return
        self.app.db.add_sync_task(s, t, b.strip(), mode)
        self.render_tasks()
        self.tabview.set("任務清單")

    def render_tasks(self):
        for w in self.scroll.winfo_children(): w.destroy()
        # 讀取時展開 5 個變數
        for tid, s, t, b, mode in self.app.db.get_sync_tasks():
            f = ctk.CTkFrame(self.scroll, fg_color=("#FFFFFF", "#2B2B2B"), corner_radius=8, border_width=1, border_color="#CCCCCC")
            f.pack(fill="x", pady=5, padx=5)
            
            # 在介面上視覺化呈現模式
            mode_icon = "➡️ 單向" if mode == "單向同步" else "↔️ 雙向"
            info_text = f"從: {s}\n到: {t}\n模式: {mode_icon} | 限速: {b if b else '無'}"
            
            ctk.CTkLabel(f, text=info_text, font=("微軟正黑體", 12, "bold"), text_color=("#111111", "#EEEEEE"), justify="left", wraplength=330).pack(side="left", padx=15, pady=10)
            ctk.CTkButton(f, text="刪除", font=("微軟正黑體", 12, "bold"), width=60, height=30, fg_color="#E63946", command=lambda x=tid: self.del_task(x)).pack(side="right", padx=15)

    def del_task(self, tid): self.app.db.delete_sync_task(tid); self.render_tasks()

    def run_tasks(self):
        tasks = self.app.db.get_sync_tasks()
        for tid, src, tgt, bw, mode in tasks:
            if not self.app.running: break
            self.execute_rclone(src, tgt, bw, mode)

    def execute_rclone(self, src, tgt, bw, mode):
        r_path = get_rclone_path()
        if not os.path.exists(r_path):
            self.app.log("❌ 找不到 rclone.exe 引擎！")
            return

        # 根據模式決定 rclone 的核心指令
        if mode == "雙向同步":
            cmd = [r_path, "bisync", src, tgt, "--progress"]
        else:
            # 單向同步 (移除了舊版的 --ignore-existing，讓修改過的檔案也能正確覆蓋更新)
            cmd = [r_path, "sync", src, tgt, "--progress"]
            
        if bw: cmd.extend(["--bwlimit", bw])
        
        self.app.log(f"🔄 [{mode}] 開始: {os.path.basename(src)}")
        
        # 宣告一個執行函數，方便重試機制使用
        def run_cmd(command):
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                     text=True, encoding='utf-8', errors='replace',
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            l_t = time.time()
            for line in process.stdout:
                if not self.app.running: process.terminate(); break
                if "Transferred:" in line and time.time() - l_t > 3:
                    self.app.log(f"[進度] {line.strip().replace('Transferred:', '')}")
                    l_t = time.time()
            process.wait()
            return process.returncode

        try:
            ret_code = run_cmd(cmd)
            
            # 🚀 智慧容錯機制：若雙向同步(bisync)因狀態遺失或首次執行失敗，自動加上 --resync 參數進行修復
            if ret_code != 0 and mode == "雙向同步" and self.app.running:
                self.app.log("⚠️ 雙向同步需要初始化或狀態重置，系統自動執行 Resync 修復...")
                cmd_resync = [r_path, "bisync", src, tgt, "--resync", "--progress"]
                if bw: cmd_resync.extend(["--bwlimit", bw])
                ret_code = run_cmd(cmd_resync)

            if self.app.running:
                if ret_code == 0:
                    self.app.log(f"✅ [{mode}] {os.path.basename(src)} 完成")
                else:
                    self.app.log(f"❌ [{mode}] 發生錯誤，請確保兩端路徑存在且擁有讀寫權限。")
                    
        except Exception as e:
            self.app.log(f"❌ 同步程式發生例外錯誤: {e}")
