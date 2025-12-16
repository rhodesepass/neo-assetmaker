#以防你不知道detect_gpus是上世纪末的遗产

import tkinter as tk
from tkinter import filedialog, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk
import os
from tqdm import tqdm
import subprocess
import shutil
import sys

print(cv2.ocl.haveOpenCL())  # 应该输出 True
cv2.ocl.setUseOpenCL(True)

import subprocess
import json
import os
import re
import threading
import time

def detect_gpus():
    """
    返回 dict:
    {
      "nvidia": ["h264_nvenc", "hevc_nvenc"],   # 存在即支持
      "intel":    ["h264_qsv",  "hevc_qsv"],
      "amd":      ["h264_amf",  "hevc_amf"],
      "mtt":      ["h264_mf",   "hevc_mf"],     # 摩尔线程走 MediaFoundation
      "cpu":      ["libx264"]                   # 兜底
    }
    以及一条推荐的 ffmpeg 模板命令列表（cmd列表）
    """
    # 1. 先找 ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"cpu": ["libx264"]}, ["-c:v", "libx264"]

    # 2. 让 ffmpeg 吐出所有编码器
    try:
        encoders = subprocess.check_output([ffmpeg, "-hide_banner", "-encoders"],
                                           text=True, encoding="utf-8")
    except Exception:
        encoders = ""

    support = {}
    if "h264_nvenc" in encoders:
        support.setdefault("nvidia", []).extend(["h264_nvenc", "hevc_nvenc"])
    if "h264_qsv" in encoders:
        support.setdefault("intel", []).extend(["h264_qsv", "hevc_qsv"])
    if "h264_amf" in encoders:
        support.setdefault("amd", []).extend(["h264_amf", "hevc_amf"])
    if "h264_mf" in encoders:
        support.setdefault("mtt", []).extend(["h264_mf", "hevc_mf"])

    # 3. 通过 WMI 把物理 GPU 名字扫出来，再交叉验证
    try:
        wmi = subprocess.check_output(
            ["wmic", "path", "win32_VideoController", "get", "name"], text=True
        )
    except Exception:
        wmi = ""

    # 简易关键字匹配
    has_n = bool(re.search(r"NVIDIA|GeForce|RTX|Quadro", wmi, re.I))
    has_a = bool(re.search(r"Radeon|RX|AMD", wmi, re.I))
    has_i = bool(re.search(r"Intel.*Arc|UHD|Iris|HD Graphics", wmi, re.I))
    has_m = bool(re.search(r"MTT|S80|S70", wmi, re.I))

    # 4. 按优先级挑一个能用的
    if has_n and "nvidia" in support:
        return support, ["-hwaccel", "cuda", "-c:v", "h264_nvenc"]
    if has_i and "intel" in support:
        return support, ["-hwaccel", "qsv", "-c:v", "h264_qsv"]
    if has_a and "amd" in support:
        return support, ["-hwaccel", "d3d11va", "-c:v", "h264_amf"]
    if has_m and "mtt" in support:
        return support, ["-c:v", "h264_mf"]      # 摩尔线程暂时无专用 hwaccel 标志

    # 5. 兜底
    support["cpu"] = ["libx264"]
    support.pop("nvidia")          # ← 加这一行
    return support, ["-c:v", "libx264"]

class VideoEditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("白银的通行证视频生成器（妈妈我要玩鸣潮）")
        self.root.geometry("1000x780")  # 稍微加高以容纳新控件

        # 视频状态
        self.cap = None
        self.video_path = ""
        self.current_frame = None
        self.display_image = None

        # 裁剪与旋转
        self.rotation = 0  # 0, 90, 180, 270
        self.crop_rect = None  # (x1, y1, x2, y2) in rotated frame
        self.dragging = False
        self.resize_mode = None
        self.lock_9_16 = True

        # 时间裁剪
        self.trim_start_var = tk.DoubleVar(value=0.0)
        self.trim_end_var = tk.DoubleVar(value=0.0)
        self.time_var = tk.DoubleVar(value=0.0)

        # 输出帧率
        self.fps_var = tk.StringVar(value="")

        # 预览窗口
        self.crop_preview_window = None
        self.crop_preview_label = None

        # 导出线程相关
        self.export_thread = None
        self.stop_export_flag = False
        self.export_process = None

        self.setup_ui()

    def setup_ui(self):
        self.control_frame = tk.Frame(self.root, width=250, bg="#f0f0f0", padx=10, pady=10)
        self.control_frame.pack(side=tk.LEFT, fill=tk.Y)

        preview_frame = tk.Frame(self.root)
        preview_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 控制按钮
        tk.Label(self.control_frame, text="视频操作", font=("Arial", 12, "bold")).pack(pady=5)
        tk.Button(self.control_frame, text="打开视频", command=self.open_video).pack(fill=tk.X, pady=5)
        tk.Button(self.control_frame, text="旋转 90°", command=self.rotate_90).pack(fill=tk.X, pady=2)
        tk.Button(self.control_frame, text="重置旋转", command=self.reset_rotation).pack(fill=tk.X, pady=2)

        # 时间裁剪
        tk.Label(self.control_frame, text="时间裁剪（秒）", font=("Arial", 10, "bold")).pack(pady=(10, 5))
        
        # 开始时间
        tk.Label(self.control_frame, text="开始时间:").pack(anchor=tk.W)
        self.trim_start_scale = tk.Scale(
            self.control_frame, from_=0, to=10, resolution=0.1,
            orient=tk.HORIZONTAL, variable=self.trim_start_var,
            command=self.on_trim_change
        )
        self.trim_start_scale.pack(fill=tk.X)
        self.trim_start_entry = tk.Entry(self.control_frame, width=10)
        self.trim_start_entry.pack(anchor=tk.W, pady=(0, 5))
        self.trim_start_entry.bind("<Return>", self.update_trim_from_entry)
        self.trim_start_var.trace_add("write", lambda *args: self._update_entry_from_var(self.trim_start_entry, self.trim_start_var))

        # 结束时间
        tk.Label(self.control_frame, text="结束时间:").pack(anchor=tk.W)
        self.trim_end_scale = tk.Scale(
            self.control_frame, from_=0, to=10, resolution=0.1,
            orient=tk.HORIZONTAL, variable=self.trim_end_var,
            command=self.on_trim_change
        )
        self.trim_end_scale.pack(fill=tk.X)
        self.trim_end_entry = tk.Entry(self.control_frame, width=10)
        self.trim_end_entry.pack(anchor=tk.W, pady=(0, 10))
        self.trim_end_entry.bind("<Return>", self.update_trim_from_entry)
        self.trim_end_var.trace_add("write", lambda *args: self._update_entry_from_var(self.trim_end_entry, self.trim_end_var))

        # 裁剪设置
        tk.Label(self.control_frame, text="裁剪框设置", font=("Arial", 10, "bold")).pack(pady=(10, 5))
        self.lock_var = tk.BooleanVar(value=True)
        tk.Checkbutton(self.control_frame, text="锁定 9:16 比例", variable=self.lock_var,
                       command=self.toggle_lock_9_16).pack(anchor=tk.W, pady=2)
        tk.Label(self.control_frame, text="• 拖动框内移动\n• 拖动右下角调整大小", fg="gray", justify=tk.LEFT).pack(anchor=tk.W)

        tk.Button(self.control_frame, text="重置裁剪框", command=self.reset_crop).pack(fill=tk.X, pady=5)

        # 输出帧率设置
        tk.Label(self.control_frame, text="输出帧率 (FPS)", font=("Arial", 10, "bold")).pack(pady=(10, 5))
        tk.Label(self.control_frame, text="留空则保持原帧率", fg="gray").pack(anchor=tk.W, pady=(0, 2))
        self.fps_entry = tk.Entry(self.control_frame, textvariable=self.fps_var, width=10)
        self.fps_entry.pack(anchor=tk.W, pady=(0, 10))

        tk.Button(self.control_frame, text="导出视频", command=self.export_video, bg="lightgreen").pack(fill=tk.X, pady=10)

        # 停止导出按钮
        self.stop_button = tk.Button(
            self.control_frame,
            text="停止导出",
            command=self.stop_export,
            bg="lightcoral",
            state=tk.DISABLED
        )
        self.stop_button.pack(fill=tk.X, pady=5)

        # 预览画布
        self.canvas = tk.Canvas(preview_frame, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

        # 时间滑块
        time_frame = tk.Frame(preview_frame)
        time_frame.pack(fill=tk.X, padx=10, pady=5)
        self.time_slider = tk.Scale(time_frame, from_=0, to=10, resolution=0.1,
                                    orient=tk.HORIZONTAL, variable=self.time_var,
                                    command=self.on_time_change, length=600)
        self.time_slider.pack()

        self.status_label = tk.Label(preview_frame, text="请先打开一个视频文件", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

    def _update_entry_from_var(self, entry_widget, var):
        try:
            current = entry_widget.get()
            new_val = f"{var.get():.1f}"
            if current != new_val:
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, new_val)
        except Exception:
            pass

    def update_trim_from_entry(self, event=None):
        try:
            start_str = self.trim_start_entry.get().strip()
            end_str = self.trim_end_entry.get().strip()

            start = float(start_str) if start_str else self.trim_start_var.get()
            end = float(end_str) if end_str else self.trim_end_var.get()

            max_time = getattr(self, 'duration', 10.0)
            start = max(0.0, min(start, max_time))
            end = max(0.0, min(end, max_time))

            if start >= end:
                end = start + 0.1
                if end > max_time:
                    start = max(0.0, max_time - 0.1)
                    end = max_time

            self.trim_start_var.set(round(start, 1))
            self.trim_end_var.set(round(end, 1))
            self.on_trim_change()

        except ValueError:
            messagebox.showwarning("输入错误", "请输入有效的数字（如 2.5）")
            self.trim_start_entry.delete(0, tk.END)
            self.trim_start_entry.insert(0, f"{self.trim_start_var.get():.1f}")
            self.trim_end_entry.delete(0, tk.END)
            self.trim_end_entry.insert(0, f"{self.trim_end_var.get():.1f}")

    def open_video(self):
        path = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv")])
        if not path:
            return
        self.video_path = path
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            messagebox.showerror("错误", "无法打开视频文件！")
            return

        fps = self.cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = total_frames / fps if fps > 0 else 0

        self.time_slider.config(to=self.duration)
        self.trim_start_scale.config(to=self.duration)
        self.trim_end_scale.config(to=self.duration)
        self.trim_end_var.set(self.duration)

        self.status_label.config(text=f"已加载: {os.path.basename(path)} | 时长: {self.duration:.1f}s")
        self.load_frame(0)

        # 初始化输入框
        self.trim_start_entry.delete(0, tk.END)
        self.trim_start_entry.insert(0, f"{self.trim_start_var.get():.1f}")
        self.trim_end_entry.delete(0, tk.END)
        self.trim_end_entry.insert(0, f"{self.trim_end_var.get():.1f}")

    def load_frame(self, time_sec):
        if not self.cap:
            return
        frame_idx = int(time_sec * self.cap.get(cv2.CAP_PROP_FPS))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if ret:
            self.current_frame = frame.copy()
            self.update_preview()

    def rotate_frame(self, frame):
        if self.rotation == 0:
            return frame
        elif self.rotation == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        elif self.rotation == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    def get_max_9_16_rect(self, w, h):
        target_ratio = 9 / 16
        if w / h > target_ratio:
            crop_h = h
            crop_w = int(h * target_ratio)
        else:
            crop_w = w
            crop_h = int(w / target_ratio)
        x1 = (w - crop_w) // 2
        y1 = (h - crop_h) // 2
        return (x1, y1, x1 + crop_w, y1 + crop_h)

    def enforce_9_16_ratio_in_rotated(self, w_rot, h_rot):
        if not self.crop_rect:
            return
        x1, y1, x2, y2 = self.crop_rect
        w = x2 - x1
        target_h = max(10, int(w * 16 / 9))
        center_y = (y1 + y2) // 2
        new_y1 = center_y - target_h // 2
        new_y2 = center_y + target_h // 2
        new_y1 = max(0, new_y1)
        new_y2 = min(h_rot, new_y2)
        if new_y2 - new_y1 < 10:
            new_y2 = new_y1 + 10
        self.crop_rect = (x1, new_y1, x2, new_y2)

    def update_preview(self):
        if self.current_frame is None:
            return

        frame = self.current_frame.copy()
        frame_rot = self.rotate_frame(frame)
        h_rot, w_rot = frame_rot.shape[:2]

        if self.crop_rect is None:
            self.crop_rect = self.get_max_9_16_rect(w_rot, h_rot)

        if self.lock_9_16:
            self.enforce_9_16_ratio_in_rotated(w_rot, h_rot)

        x1, y1, x2, y2 = self.crop_rect
        cv2.rectangle(frame_rot, (x1, y1), (x2, y2), (0, 255, 0), 2)
        handle_size = 8
        cv2.rectangle(frame_rot, (x2 - handle_size, y2 - handle_size), (x2, y2), (255, 0, 0), -1)

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        if canvas_w <= 1 or canvas_h <= 1:
            self.root.after(100, self.update_preview)
            return

        scale = min(canvas_w / w_rot, canvas_h / h_rot)
        new_w, new_h = int(w_rot * scale), int(h_rot * scale)
        resized = cv2.resize(frame_rot, (new_w, new_h))

        img_rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        self.display_image = ImageTk.PhotoImage(pil_img)

        self.canvas.delete("all")
        self.canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.display_image)

        # 裁剪预览窗口
        try:
            cropped = frame_rot[y1:y2, x1:x2]
            if cropped.size > 0:
                preview_h, preview_w = cropped.shape[:2]
                target_h = 356
                target_w = int(target_h * 9 / 16)
                preview_resized = cv2.resize(cropped, (target_w, target_h))
                preview_rgb = cv2.cvtColor(preview_resized, cv2.COLOR_BGR2RGB)
                preview_pil = Image.fromarray(preview_rgb)

                if self.crop_preview_window is None:
                    self.crop_preview_window = tk.Toplevel(self.root, bd=2)
                    self.crop_preview_window.attributes('-topmost', True)
                    self.crop_preview_window.overrideredirect(False)  # 保留窗口边框
                    self.crop_preview_window.iconphoto(False, tk.PhotoImage(file="settings.png"))
                    self.crop_preview_window.title("裁剪预览 (9:16)（妈妈我要玩明日方舟终末地！！！）")
                    self.crop_preview_window.geometry("240x380")
                    self.crop_preview_label = tk.Label(self.crop_preview_window)
                    self.crop_preview_label.pack()

                    screen_width = self.root.winfo_screenwidth()
                    window_width = 240
                    window_height = 380
                    x_position = screen_width - window_width - 100  # 离右侧50像素
                    y_position = 100  # 离顶部50像素
                    self.crop_preview_window.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")

                    def on_close():
                        self.crop_preview_window.destroy()
                        self.crop_preview_window = None
                        self.crop_preview_label = None
                    self.crop_preview_window.protocol("WM_DELETE_WINDOW", on_close)

                preview_tk = ImageTk.PhotoImage(preview_pil)
                self.crop_preview_label.config(image=preview_tk)
                self.crop_preview_label.image = preview_tk
        except Exception as e:
            print("裁剪预览更新失败:", e)


    def on_time_change(self, value):
        self.load_frame(float(value))

    def on_trim_change(self, _=None):
        start = self.trim_start_var.get()
        end = self.trim_end_var.get()
        if start >= end:
            self.trim_end_var.set(start + 0.1)
        self.time_var.set(start)
        self.load_frame(start)

    def rotate_90(self):
        self.rotation = (self.rotation + 90) % 360
        self.crop_rect = None
        self.update_preview()

    def reset_rotation(self):
        self.rotation = 0
        self.crop_rect = None
        self.update_preview()

    def reset_crop(self):
        self.crop_rect = None
        self.update_preview()

    def toggle_lock_9_16(self):
        self.lock_9_16 = self.lock_var.get()
        if self.lock_9_16 and self.crop_rect:
            frame_rot = self.rotate_frame(self.current_frame.copy())
            h_rot, w_rot = frame_rot.shape[:2]
            self.enforce_9_16_ratio_in_rotated(w_rot, h_rot)
            self.update_preview()

    # 裁剪框交互
    def on_canvas_click(self, event):
        if self.current_frame is None:
            return
        frame_rot = self.rotate_frame(self.current_frame.copy())
        h_rot, w_rot = frame_rot.shape[:2]
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        scale = min(cw / w_rot, ch / h_rot)
        offset_x = (cw - w_rot * scale) / 2
        offset_y = (ch - h_rot * scale) / 2

        img_x = int((event.x - offset_x) / scale)
        img_y = int((event.y - offset_y) / scale)

        x1, y1, x2, y2 = self.crop_rect or (0, 0, w_rot, h_rot)
        margin = max(20, min(50, int(w_rot * 0.02)))

        if abs(img_x - x2) < margin and abs(img_y - y2) < margin:
            self.resize_mode = 'br'
            self.dragging = True
        elif x1 <= img_x <= x2 and y1 <= img_y <= y2:
            self.resize_mode = 'move'
            self.dragging = True
            self.start_x, self.start_y = img_x, img_y
        else:
            self.dragging = False

    def on_canvas_drag(self, event):
        if not self.dragging or self.current_frame is None:
            return
        frame_rot = self.rotate_frame(self.current_frame.copy())
        h_rot, w_rot = frame_rot.shape[:2]
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        scale = min(cw / w_rot, ch / h_rot)
        offset_x = (cw - w_rot * scale) / 2
        offset_y = (ch - h_rot * scale) / 2

        img_x = max(0, min(w_rot, int((event.x - offset_x) / scale)))
        img_y = max(0, min(h_rot, int((event.y - offset_y) / scale)))

        x1, y1, x2, y2 = self.crop_rect

        if self.resize_mode == 'br':
            new_x2 = max(x1 + 20, img_x)
            if self.lock_9_16:
                new_w = new_x2 - x1
                new_h = int(new_w * 16 / 9)
                new_y2 = y1 + new_h
                if new_y2 > h_rot:
                    new_y2 = h_rot
                    new_h = h_rot - y1
                    new_w = int(new_h * 9 / 16)
                    new_x2 = x1 + new_w
                self.crop_rect = (x1, y1, new_x2, new_y2)
            else:
                new_y2 = max(y1 + 20, img_y)
                self.crop_rect = (x1, y1, new_x2, new_y2)
        elif self.resize_mode == 'move':
            dx = img_x - self.start_x
            dy = img_y - self.start_y
            nx1, ny1 = x1 + dx, y1 + dy
            nx2, ny2 = x2 + dx, y2 + dy
            if nx1 < 0: nx1, nx2 = 0, x2 - x1
            if ny1 < 0: ny1, ny2 = 0, y2 - y1
            if nx2 > w_rot: nx2, nx1 = w_rot, w_rot - (x2 - x1)
            if ny2 > h_rot: ny2, ny1 = h_rot, h_rot - (y2 - y1)
            self.crop_rect = (max(0, nx1), max(0, ny1), min(w_rot, nx2), min(h_rot, ny2))
            self.start_x, self.start_y = img_x, img_y

        self.update_preview()

    def on_canvas_release(self, event):
        self.dragging = False
        self.resize_mode = None
        if self.lock_9_16 and self.crop_rect:
            frame_rot = self.rotate_frame(self.current_frame.copy())
            h_rot, w_rot = frame_rot.shape[:2]
            self.enforce_9_16_ratio_in_rotated(w_rot, h_rot)
            self.update_preview()

    # 导出视频相关方法
    def update_export_status(self, elapsed_time):
        """更新导出状态（在主线程中调用）"""
        self.status_label.config(text=f"正在生成视频，已生成 {elapsed_time}")
        self.root.update_idletasks()
    
    def run_ffmpeg_thread(self, cmd, save_path, startupinfo):
        """在后台线程中运行 FFmpeg"""
        try:
            # 创建进程
            self.export_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # 合并stdout和stderr
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                bufsize=1  # 行缓冲
            )
            
            # 实时读取输出
            while True:
                if self.stop_export_flag:
                    if self.export_process:
                        self.export_process.terminate()
                    break
                
                line = self.export_process.stdout.readline()
                if not line:
                    # 检查进程是否结束
                    if self.export_process.poll() is not None:
                        break
                    # 等待一下再检查
                    time.sleep(0.05)
                    continue
                
                # 在控制台输出便于调试
                print(line.strip())
                
                # 查找 elapsed 信息（FFmpeg 格式）
                elapsed_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                if elapsed_match:
                    elapsed_time = elapsed_match.group(1)
                    # 使用 after 在主线程中更新 UI
                    self.root.after(0, lambda t=elapsed_time: self.update_export_status(t))
                
                # 查找 speed 信息
                speed_match = re.search(r"speed=\s*([\d.]+)x", line)
                if speed_match:
                    speed = speed_match.group(1)
                    self.root.after(0, lambda s=speed: self.update_speed_status(s))
            
            # 等待进程结束
            self.export_process.wait()
            
            # 读取剩余输出
            remaining_output = self.export_process.stdout.read()
            if remaining_output:
                print(remaining_output.strip())
            
            # 在主线程中显示结果
            if self.export_process.returncode == 0:
                self.root.after(0, lambda: self.on_export_success(save_path))
            else:
                self.root.after(0, self.on_export_failed)
                
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.on_export_error(err))
        finally:
            self.export_thread = None
            self.stop_export_flag = False
            self.export_process = None
            self.root.after(0, self.on_export_finished)
    
    def update_speed_status(self, speed):
        """更新速度信息"""
        current_text = self.status_label.cget("text")
        if "速度" not in current_text:
            self.status_label.config(text=f"{current_text} (速度: {speed}x)")
            self.root.update_idletasks()
    
    def on_export_success(self, save_path):
        """导出成功回调"""
        messagebox.showinfo("成功", f"视频已导出至:\n{save_path}")
        self.status_label.config(text="就绪")
    
    def on_export_failed(self):
        """导出失败回调"""
        messagebox.showerror("导出失败", "FFmpeg 执行失败，请查看控制台输出")
        self.status_label.config(text="导出失败")
    
    def on_export_error(self, error_msg):
        """导出错误回调"""
        messagebox.showerror("错误", f"导出过程中发生异常:\n{error_msg}")
        self.status_label.config(text="就绪")
    
    def on_export_finished(self):
        """导出完成回调"""
        self.stop_button.config(state=tk.DISABLED)
    
    def stop_export(self):
        """停止导出"""
        if self.export_thread and self.export_thread.is_alive():
            self.stop_export_flag = True
            if self.export_process:
                self.export_process.terminate()
            self.status_label.config(text="正在停止导出...")
            self.root.update_idletasks()

    # 导出视频（先旋转再裁剪）
    def export_video(self):
        gpu_support, codec_cmd = detect_gpus()
        print("[GPU] 探测结果:", gpu_support, codec_cmd)
        if not self.video_path:
            messagebox.showwarning("警告", "请先打开视频！")
            return
        if self.trim_start_var.get() >= self.trim_end_var.get():
            messagebox.showwarning("警告", "结束时间必须大于开始时间！")
            return
        if self.crop_rect is None:
            messagebox.showwarning("警告", "裁剪框未初始化！")
            return

        # 检查 ffmpeg 
        if shutil.which("ffmpeg") is None:
            messagebox.showerror("错误", "未找到 FFmpeg！\n请安装 FFmpeg 并确保它在系统 PATH 中。（起码你得手动指定一个。。。）")
            return

        save_path = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")]
        )
        if not save_path:
            return

        try:
            # 获取原始帧用于尺寸参考（仅用于 crop 坐标）
            cap = cv2.VideoCapture(self.video_path)
            cv2.ocl.setUseOpenCL(True)
            ret, frame0 = cap.read()
            cap.release()
            if not ret:
                raise RuntimeError("无法读取参考帧")

            # 应用旋转，获取旋转后尺寸（验证 crop）
            frame0_rot = self.rotate_frame(frame0)
            h_rot, w_rot = frame0_rot.shape[:2]

            x1, y1, x2, y2 = [int(v) for v in self.crop_rect]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w_rot, x2), min(h_rot, y2)
            crop_w = x2 - x1
            crop_h = y2 - y1

            if crop_w <= 0 or crop_h <= 0:
                raise ValueError("裁剪区域无效")

            # 解析输出帧率
            fps_output = None
            fps_str = self.fps_var.get().strip()
            if fps_str:
                try:
                    fps_output = float(fps_str)
                    if fps_output <= 0:
                        raise ValueError("帧率必须为正数")
                    if fps_output >= 381:
                        raise ValueError("帧率不能大于380！")
                except ValueError as e:
                    messagebox.showerror("帧率错误", f"无效的帧率输入：{e}")
                    return

            # FFmpeg 滤镜
            vf_filters = []

            # 旋转
            if self.rotation == 90:
                vf_filters.append("transpose=1")
            elif self.rotation == 180:
                vf_filters.append("hflip,vflip")
            elif self.rotation == 270:
                vf_filters.append("transpose=2")

            # 裁剪
            vf_filters.append(f"crop={crop_w}:{crop_h}:{x1}:{y1}")

            # 缩放到 360x640（9:16）
            vf_filters.append("scale=360:640:force_original_aspect_ratio=decrease")

            # 填充384x640，靠右（左侧留 24黑边）
            vf_filters.append("pad=384:640:24:0:color=black")

            # 强制输出NV12
            vf_filters.append("format=nv12")

            vf_str = ",".join(vf_filters)

            start_time = self.trim_start_var.get()
            duration = self.trim_end_var.get() - start_time

            # 构建 FFmpeg 命令
            cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(start_time),
                "-i", self.video_path,
                "-t", str(duration),
                "-vf", vf_str,
            ]
            
            if fps_output is not None:
                cmd.extend(["-r", str(fps_output)])

            cmd.extend([
                "-c:v", "libx264",
                "-pix_fmt", "nv12",
                "-crf", "23",
                "-preset", "fast",
                "-c:a", "aac",
                "-b:a", "128k",
                "-progress", "pipe:1",  # 强制输出进度信息到stdout
                "-loglevel", "info",    # 确保有进度输出
                save_path
            ])

            # 显示初始状态
            self.status_label.config(text="正在生成视频...")
            self.stop_button.config(state=tk.NORMAL)
            self.root.update()
            
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            # 停止可能正在运行的导出
            self.stop_export()
            
            # 重置标志并启动新线程
            self.stop_export_flag = False
            
            # 在新线程中运行 FFmpeg
            self.export_thread = threading.Thread(
                target=self.run_ffmpeg_thread,
                args=(cmd, save_path, startupinfo),
                daemon=True
            )
            self.export_thread.start()

        except Exception as e:
            messagebox.showerror("错误", f"导出过程中发生异常:\n{str(e)}")
            self.status_label.config(text="就绪")
            self.stop_button.config(state=tk.DISABLED)


if __name__ == "__main__":
    root = tk.Tk()
    root.iconphoto(True, tk.PhotoImage(file="app.png"))
    app = VideoEditorApp(root)
    root.mainloop()
