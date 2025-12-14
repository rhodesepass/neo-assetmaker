# setup.py
import sys
import os
from cx_Freeze import setup, Executable

# 基础设置
build_exe_options = {
    "packages": [
        "tkinter", 
        "PIL",
        "bs4",
        "cv2",
        "numpy",
        "PIL",
        "tqdm",
        "subprocess",
        "shutil"
    ],
    "includes": [
        "PIL._tkinter_finder",
        "PIL._imaging",
    ],
    "include_files": [
        (".gitignore", ".gitignore"),  # 包含缓存目录
        ("settings.png", "settings.png"),
        ("README.MD", "README.MD"),
        ("app.png", "app.png")
    ],
    "excludes": [
        "test", 
        "unittest",
        "email",
        "http",
        "ftplib",
        "pydoc",
        "pdb"
    ],
    "optimize": 2,
}

# 平台特定设置
base = None
'''
if sys.platform == "win32":
    base = "Win32GUI"  # 无控制台窗口
'''

# 主程序配置
executables = [
    Executable(
        "main.py",
        base=base,
        target_name="neo-assetmaker.exe",
        uac_admin=True,  # 请求管理员权限
        icon="icon.ico" if os.path.exists("icon.ico") else None,
    )
]

setup(
    name="图形化素材制作器",
    version="1.0.0",
    description="图形化素材制作器",
    options={"build_exe": build_exe_options},
    executables=executables
)
