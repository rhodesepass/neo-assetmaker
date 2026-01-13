"""
明日方舟通行证素材制作器 - cx_Freeze 打包工具
ArknightsPassMaker - cx_Freeze Build Tool
"""
import os
import sys
import subprocess
import argparse
import shutil

# 增加递归限制，解决 cx_Freeze 打包大型包时的问题
sys.setrecursionlimit(10000)

PROJECT_NAME = "ArknightsPassMaker"
VERSION = "1.0.1"
MAIN_SCRIPT = "main.py"
ICON_FILE = "resources/icons/favicon.ico"
BUILD_DIR = PROJECT_NAME
DIST_DIR = "dist"


def parse_args():
    parser = argparse.ArgumentParser(
        description=f"{PROJECT_NAME} - cx_Freeze + 7Z_SFX Build Tool"
    )
    parser.add_argument(
        '--no-sfx',
        action='store_true',
        help='Skip 7Z_SFX packaging, only run cx_Freeze.'
    )
    parser.add_argument(
        '--clean',
        action='store_true',
        help='Clean build directories before building.'
    )
    return parser.parse_args()


def get_site_packages():
    """获取 site-packages 路径"""
    return os.path.join(sys.prefix, "Lib", "site-packages")


def check_requirements():
    """检查构建环境"""
    print("Checking build environment...")

    # 检查 cx_Freeze
    try:
        import cx_Freeze
        print(f"cx_Freeze version: {cx_Freeze.__version__}")
    except ImportError:
        print("Error: cx_Freeze not installed")
        print("Run: pip install cx_Freeze")
        return False

    # 检查主脚本
    if not os.path.exists(MAIN_SCRIPT):
        print(f"Error: Main script {MAIN_SCRIPT} not found")
        return False

    # 检查图标
    if os.path.exists(ICON_FILE):
        print(f"Icon file: {ICON_FILE} found")
    else:
        print(f"Warning: Icon file {ICON_FILE} not found")

    # 检查 ffmpeg
    if os.path.exists("ffmpeg.exe"):
        print("ffmpeg.exe: found")
    else:
        print("Warning: ffmpeg.exe not found, video export may not work")

    # 检查 7-Zip (用于 SFX)
    sevenzip_paths = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    sevenzip_found = False
    for path in sevenzip_paths:
        if os.path.exists(path):
            print(f"7-Zip: found at {path}")
            sevenzip_found = True
            break
    if not sevenzip_found:
        print("Warning: 7-Zip not found, SFX packaging will be skipped")

    # 检查 SFX 模块是否在项目文件夹
    check_sfx_module()

    return True


def check_sfx_module():
    """检查 SFX 模块是否在项目文件夹，如果不存在则尝试复制"""
    local_sfx_files = ["7zSD.sfx", "7z.sfx"]

    # 检查本地是否已存在
    for sfx in local_sfx_files:
        if os.path.exists(sfx):
            print(f"SFX module: {sfx} found")
            return True

    # 尝试从 7-Zip 安装目录复制
    system_sfx_paths = [
        r"C:\Program Files\7-Zip\7z.sfx",
        r"C:\Program Files (x86)\7-Zip\7z.sfx",
    ]

    for src_path in system_sfx_paths:
        if os.path.exists(src_path):
            try:
                shutil.copy(src_path, "7z.sfx")
                print(f"SFX module: copied from {src_path}")
                return True
            except Exception as e:
                print(f"Warning: Failed to copy SFX module: {e}")

    print("Warning: SFX module not found in project folder")
    print("  Please download 7zSD.sfx from https://www.7-zip.org/sdk.html")
    print("  Or copy 7z.sfx from 7-Zip installation directory")
    return False


def clean_build():
    """清理构建目录"""
    print("Cleaning build directories...")
    dirs_to_clean = [BUILD_DIR, DIST_DIR]
    for d in dirs_to_clean:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"  Removed: {d}")


def run_cxfreeze():
    """执行 cx_Freeze 打包"""
    from cx_Freeze import setup, Executable

    site_packages = get_site_packages()

    # 需要包含的包
    packages = [
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "cv2",
        "PIL",
        "numpy",
        "jsonschema",
        "thefuzz",
        "Levenshtein",
        "easyocr",
        "torch",
        "logging",
        "json",
        "uuid",
        "dataclasses",
    ]

    # 包含自定义模块
    includes = [
        "config",
        "config.constants",
        "config.epconfig",
        "core",
        "core.validator",
        "core.video_processor",
        "core.image_processor",
        "core.export_service",
        "core.legacy_converter",
        "core.overlay_renderer",
        "core.operator_lookup",
        "core.ocr_service",
        "gui",
        "gui.main_window",
        "gui.dialogs",
        "gui.dialogs.export_progress_dialog",
        "gui.dialogs.operator_confirm_dialog",
        "gui.widgets",
        "gui.widgets.config_panel",
        "gui.widgets.video_preview",
        "gui.widgets.timeline",
        "gui.widgets.json_preview",
        "utils",
        "utils.logger",
        "utils.file_utils",
        "utils.color_utils",
    ]

    # 排除包
    excludes = [
        "tkinter",
        "unittest",
        "test",
        "tests",
        "pytest",
        "IPython",
        "notebook",
        "jupyter",
        # torch 相关排除
        "torch.testing",
        "torch.utils.tensorboard",
        "torch.utils.benchmark",
        "torch.distributed",
        "torchvision",
        "torchaudio",
        # 其他
        "scipy.spatial.cKDTree",
        "sympy",
    ]

    # 构建 include_files
    include_files = [
        ("resources", "resources"),
    ]

    # 添加 ffmpeg
    if os.path.exists("ffmpeg.exe"):
        include_files.append(("ffmpeg.exe", "ffmpeg.exe"))

    # 添加 PyQt6 插件
    pyqt6_plugins_path = os.path.join(site_packages, "PyQt6", "Qt6", "plugins")
    if os.path.exists(pyqt6_plugins_path):
        plugins_to_include = ["platforms", "imageformats", "styles"]
        for plugin in plugins_to_include:
            plugin_path = os.path.join(pyqt6_plugins_path, plugin)
            if os.path.exists(plugin_path):
                include_files.append(
                    (plugin_path, os.path.join("lib", "PyQt6", "Qt6", "plugins", plugin))
                )

    build_exe_options = {
        "packages": packages,
        "includes": includes,
        "excludes": excludes,
        "include_files": include_files,
        "optimize": 2,
        "build_exe": BUILD_DIR,
    }

    # Windows GUI 应用
    base = "Win32GUI" if sys.platform == "win32" else None

    # 保存原始 sys.argv
    original_argv = sys.argv
    sys.argv = [sys.argv[0], "build"]

    try:
        setup(
            name=PROJECT_NAME,
            version=VERSION,
            description="明日方舟通行证素材制作器",
            author="ArknightsPassMaker",
            options={"build_exe": build_exe_options},
            executables=[
                Executable(
                    script=MAIN_SCRIPT,
                    base=base,
                    target_name=f"{PROJECT_NAME}.exe",
                    icon=ICON_FILE if os.path.exists(ICON_FILE) else None,
                )
            ],
        )
        # 删除 frozen_application_license.txt
        license_file = os.path.join(BUILD_DIR, "frozen_application_license.txt")
        if os.path.exists(license_file):
            os.remove(license_file)
        return True
    except Exception as e:
        print(f"cx_Freeze build failed: {e}")
        return False
    finally:
        sys.argv = original_argv


def create_sfx_config():
    """创建 SFX 配置文件"""
    config_content = f""";!@Install@!UTF-8!
Title="{PROJECT_NAME} v{VERSION}"
BeginPrompt="是否安装 明日方舟通行证素材制作器？"
ExtractDialogText="正在解压文件，请稍候..."
ExtractTitle="安装中"
GUIFlags="8+32+64"
OverwriteMode="1"
RunProgram="{PROJECT_NAME}.exe"
;!@InstallEnd@!
"""
    config_path = "sfx_config.txt"
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config_content)
    return config_path


def find_7zip():
    """查找 7-Zip 可执行文件"""
    paths = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def find_sfx_module():
    """查找 SFX 模块"""
    # 优先使用项目目录下的
    local_sfx = ["7zSD.sfx", "7z.sfx"]
    for sfx in local_sfx:
        if os.path.exists(sfx):
            return sfx

    # 从 7-Zip 安装目录查找
    paths = [
        r"C:\Program Files\7-Zip\7z.sfx",
        r"C:\Program Files (x86)\7-Zip\7z.sfx",
    ]
    for path in paths:
        if os.path.exists(path):
            return path

    return None


def create_sfx():
    """创建 7Z_SFX 自解压安装包"""
    print("\n" + "=" * 50)
    print("Creating 7Z_SFX package...")
    print("=" * 50)

    sevenzip = find_7zip()
    if not sevenzip:
        print("Error: 7-Zip not found, skipping SFX packaging")
        return False

    sfx_module = find_sfx_module()
    if not sfx_module:
        print("Error: SFX module (7zSD.sfx or 7z.sfx) not found")
        print("Please download from https://www.7-zip.org/sdk.html")
        print("Or copy 7z.sfx from 7-Zip installation directory")
        return False

    # 确保 dist 目录存在
    os.makedirs(DIST_DIR, exist_ok=True)

    # 创建 SFX 配置
    sfx_config = create_sfx_config()

    # 临时 7z 文件
    temp_7z = "temp_app.7z"

    # 输出文件名
    output_file = os.path.join(DIST_DIR, f"{PROJECT_NAME}_v{VERSION}_Setup.exe")

    try:
        # Step 1: 压缩 build 目录
        print("Compressing files...")
        cmd = [
            sevenzip, "a", "-t7z", "-mx=9", "-mf=BCJ2", "-r",
            temp_7z, f"{BUILD_DIR}/*"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Compression failed: {result.stderr}")
            return False

        # Step 2: 合并 SFX
        print("Creating SFX installer...")
        with open(output_file, "wb") as out:
            # SFX 模块
            with open(sfx_module, "rb") as f:
                out.write(f.read())
            # 配置文件
            with open(sfx_config, "rb") as f:
                out.write(f.read())
            # 7z 压缩包
            with open(temp_7z, "rb") as f:
                out.write(f.read())

        # 获取文件大小
        file_size = os.path.getsize(output_file)
        print(f"\nSFX package created: {output_file}")
        print(f"File size: {file_size / 1024 / 1024:.2f} MB")

        return True

    finally:
        # 清理临时文件
        if os.path.exists(temp_7z):
            os.remove(temp_7z)
        if os.path.exists(sfx_config):
            os.remove(sfx_config)


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    args = parse_args()

    print("=" * 50)
    print(f"  {PROJECT_NAME} - cx_Freeze + 7Z_SFX Build Tool")
    print(f"  Version: {VERSION}")
    print("=" * 50)

    if not check_requirements():
        sys.exit(1)

    if args.clean:
        clean_build()

    # Step 1: cx_Freeze 打包
    print("\n" + "=" * 50)
    print("Running cx_Freeze build...")
    print("=" * 50)

    if not run_cxfreeze():
        print("\ncx_Freeze build failed!")
        sys.exit(1)

    print("\ncx_Freeze build successful!")
    print(f"Output: {BUILD_DIR}/")

    # Step 2: 7Z_SFX 打包 (可选)
    if not args.no_sfx:
        if create_sfx():
            print("\n" + "=" * 50)
            print("Build completed successfully!")
            print("=" * 50)
        else:
            print("\nSFX packaging skipped or failed")
            print("You can still use the files in build/ directory")
    else:
        print("\nSFX packaging skipped (--no-sfx)")

    sys.exit(0)


if __name__ == "__main__":
    main()
