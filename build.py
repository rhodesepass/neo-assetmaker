"""
明日方舟通行证素材制作器 - cx_Freeze + Inno Setup 打包工具
"""
import os
import sys
import subprocess
import argparse
import shutil
import urllib.request
import zipfile

sys.setrecursionlimit(10000)

PROJECT_NAME = "ArknightsPassMaker"
VERSION = "1.5.7"
MAIN_SCRIPT = "main.py"
ICON_FILE = "resources/icons/favicon.ico"
BUILD_DIR = PROJECT_NAME
DIST_DIR = "dist"
ISS_FILE = "installer.iss"
INNO_SETUP_DIR = "tools/innosetup"


def parse_args():
    parser = argparse.ArgumentParser(description=f"{PROJECT_NAME} Build Tool")
    parser.add_argument('--no-installer', action='store_true', help='Skip installer packaging')
    parser.add_argument('--clean', action='store_true', help='Clean build directories')
    parser.add_argument('--skip-flasher', action='store_true', help='Skip epass_flasher build (not recommended)')
    return parser.parse_args()


def get_site_packages():
    return os.path.join(sys.prefix, "Lib", "site-packages")


def download_inno_setup():
    """下载 Inno Setup 便携版"""
    iscc_path = os.path.join(INNO_SETUP_DIR, "ISCC.exe")
    if os.path.exists(iscc_path):
        return iscc_path

    print("Downloading Inno Setup...")
    os.makedirs(INNO_SETUP_DIR, exist_ok=True)

    url = "https://files.jrsoftware.org/is/6/innosetup-6.4.3.exe"
    installer_path = os.path.join(INNO_SETUP_DIR, "innosetup.exe")

    try:
        urllib.request.urlretrieve(url, installer_path)
        print("Installing Inno Setup (silent)...")
        subprocess.run([
            installer_path, "/VERYSILENT", "/SUPPRESSMSGBOXES",
            "/NORESTART", f"/DIR={os.path.abspath(INNO_SETUP_DIR)}"
        ], check=True, capture_output=True)
        os.remove(installer_path)

        if os.path.exists(iscc_path):
            print(f"Inno Setup installed: {iscc_path}")
            return iscc_path
    except Exception as e:
        print(f"Failed to download Inno Setup: {e}")

    return None


def find_inno_setup():
    """查找 Inno Setup"""
    local_iscc = os.path.join(INNO_SETUP_DIR, "ISCC.exe")
    if os.path.exists(local_iscc):
        return local_iscc

    paths = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def check_uv():
    """检查 uv 是否可用"""
    try:
        result = subprocess.run(["uv", "--version"], capture_output=True, check=True)
        version = result.stdout.decode().strip()
        print(f"  uv: {version}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def build_epass_flasher():
    """构建 epass_flasher.exe"""
    flasher_dir = "epass_flasher"
    flasher_exe = os.path.join(flasher_dir, "dist", "epass_flasher.exe")

    # 检查目录是否存在
    if not os.path.exists(flasher_dir):
        print("  Warning: epass_flasher directory not found")
        return False

    # 检查子模块是否已初始化
    flasher_pyproject = os.path.join(flasher_dir, "pyproject.toml")
    if not os.path.exists(flasher_pyproject):
        print("  ERROR: epass_flasher submodule not initialized")
        print("         Run: git submodule update --init --recursive")
        print("         Or in CI: add 'submodules: true' to actions/checkout")
        return False

    # 如果已存在且比源文件新，跳过构建
    flasher_main = os.path.join(flasher_dir, "main.py")
    if os.path.exists(flasher_exe) and os.path.exists(flasher_main):
        if os.path.getmtime(flasher_exe) > os.path.getmtime(flasher_main):
            print("  epass_flasher.exe is up to date")
            return True

    print("Building epass_flasher...")

    # 检查 uv 是否可用
    if not check_uv():
        print("  Warning: uv not found, skipping epass_flasher build")
        return False

    # CI 中删除 uv.lock，强制使用 UV_DEFAULT_INDEX 环境变量指定的源
    # （epass_flasher 的 uv.lock 锁定了清华镜像 URL，CI 无法访问）
    lock_file = os.path.join(flasher_dir, "uv.lock")
    if os.environ.get("UV_DEFAULT_INDEX") and os.path.exists(lock_file):
        print("  Removing uv.lock to use UV_DEFAULT_INDEX...")
        os.remove(lock_file)

    # 同步依赖（--group dev: 安装 dev 依赖，包含 PyInstaller）
    print("  Syncing dependencies...")
    result = subprocess.run(
        ["uv", "sync", "--group", "dev"],
        cwd=flasher_dir
    )
    if result.returncode != 0:
        print("  ERROR: uv sync failed")
        return False

    # 使用 PyInstaller 打包（不捕获输出，让用户看到完整错误信息）
    print("  Running PyInstaller...")
    result = subprocess.run(
        ["uv", "run", "pyinstaller", "main.spec", "--clean", "-y"],
        cwd=flasher_dir
    )
    if result.returncode != 0:
        print("  ERROR: PyInstaller failed, see error messages above")
        return False

    if os.path.exists(flasher_exe):
        print(f"  Built: {flasher_exe}")
        return True
    else:
        print("  Warning: epass_flasher.exe not found after build")
        return False


def check_requirements():
    """检查构建环境"""
    print("Checking build environment...")

    # 检查 uv
    if not check_uv():
        print("  uv: not found (epass_flasher will not be built)")

    try:
        import cx_Freeze
        print(f"  cx_Freeze: {cx_Freeze.__version__}")
    except ImportError:
        print("Error: cx_Freeze not installed")
        return False

    if not os.path.exists(MAIN_SCRIPT):
        print(f"Error: {MAIN_SCRIPT} not found")
        return False

    print(f"  ffmpeg.exe: {'found' if os.path.exists('ffmpeg.exe') else 'not found'}")
    print(f"  ffprobe.exe: {'found' if os.path.exists('ffprobe.exe') else 'not found'}")

    iscc = find_inno_setup()
    if iscc:
        print(f"  Inno Setup: found")
    else:
        print("  Inno Setup: not found (will download)")

    return True


def clean_build():
    """清理构建目录"""
    print("Cleaning...")
    for d in [BUILD_DIR, DIST_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"  Removed: {d}")

    # 清理所有 __pycache__ 目录，确保使用最新源代码
    print("Cleaning __pycache__ directories...")
    for root, dirs, files in os.walk('.'):
        if '__pycache__' in dirs:
            cache_path = os.path.join(root, '__pycache__')
            shutil.rmtree(cache_path)
            print(f"  Removed cache: {cache_path}")


def run_cxfreeze(skip_flasher=False):
    """执行 cx_Freeze 打包"""
    # 先构建 epass_flasher
    if not skip_flasher:
        if not build_epass_flasher():
            print("\nERROR: epass_flasher build failed, aborting")
            print("       Use --skip-flasher to skip this check (not recommended)")
            return False
    else:
        print("Skipping epass_flasher build (--skip-flasher)")


    # 强制清理 __pycache__，确保使用最新源代码编译
    print("Clearing __pycache__ before build...")
    for root, dirs, files in os.walk('.'):
        if '__pycache__' in dirs:
            cache_path = os.path.join(root, '__pycache__')
            shutil.rmtree(cache_path)
            print(f"  Cleared: {cache_path}")

    from cx_Freeze import setup, Executable

    site_packages = get_site_packages()

    packages = [
        "PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets",
        "cv2", "PIL", "numpy", "jsonschema", "thefuzz",
        "logging", "json", "uuid", "dataclasses",
    ]

    includes = [
        "config", "config.constants", "config.epconfig",
        "core", "core.validator", "core.video_processor", "core.image_processor",
        "core.export_service", "core.overlay_renderer",
        "core.update_service",
        "gui", "gui.main_window", "gui.dialogs",
        "gui.dialogs.export_progress_dialog", "gui.dialogs.welcome_dialog",
        "gui.dialogs.shortcuts_dialog", "gui.dialogs.update_dialog",
        "gui.widgets", "gui.widgets.config_panel",
        "gui.widgets.video_preview", "gui.widgets.timeline", "gui.widgets.json_preview",
        "utils", "utils.logger", "utils.file_utils", "utils.color_utils",
    ]

    excludes = [
        "tkinter", "unittest", "test", "tests", "pytest", "IPython",
        "notebook", "jupyter", "torch.testing", "torch.utils.tensorboard",
        "torch.utils.benchmark", "torch.distributed", "torchvision",
        "torchaudio", "scipy.spatial.cKDTree", "sympy",
    ]

    include_files = [("resources", "resources")]
    if os.path.exists("ffmpeg.exe"):
        include_files.append(("ffmpeg.exe", "ffmpeg.exe"))
    if os.path.exists("ffprobe.exe"):
        include_files.append(("ffprobe.exe", "ffprobe.exe"))

    # 添加 Rust 模拟器
    simulator_exe = os.path.join("simulator", "target", "release", "arknights_pass_simulator.exe")
    if os.path.exists(simulator_exe):
        # 创建目标目录结构
        target_path = os.path.join("simulator", "target", "release", "arknights_pass_simulator.exe")
        include_files.append((simulator_exe, target_path))
        print(f"  Including simulator: {simulator_exe}")

    # 添加 FFmpeg DLL（模拟器运行时依赖）
    ffmpeg_sdk_bin = os.path.join("ffmpeg-sdk", "bin")
    if os.path.exists(ffmpeg_sdk_bin):
        for dll in os.listdir(ffmpeg_sdk_bin):
            if dll.endswith(".dll"):
                src = os.path.join(ffmpeg_sdk_bin, dll)
                include_files.append((src, dll))
                print(f"  Including FFmpeg DLL: {dll}")

    # 添加烧录工具
    flasher_exe = os.path.join("epass_flasher", "dist", "epass_flasher.exe")
    if os.path.exists(flasher_exe):
        include_files.append((flasher_exe, "epass_flasher.exe"))
        print(f"  Including flasher: {flasher_exe}")
    elif not skip_flasher:
        print("\nERROR: epass_flasher.exe not found, aborting")
        print("       Use --skip-flasher to skip this check (not recommended)")
        return False
    else:
        print("  Warning: epass_flasher.exe not found (skipped due to --skip-flasher)")

    pyqt6_plugins = os.path.join(site_packages, "PyQt6", "Qt6", "plugins")
    if os.path.exists(pyqt6_plugins):
        for plugin in ["platforms", "imageformats", "styles"]:
            plugin_path = os.path.join(pyqt6_plugins, plugin)
            if os.path.exists(plugin_path):
                include_files.append((plugin_path, f"lib/PyQt6/Qt6/plugins/{plugin}"))

    build_options = {
        "packages": packages,
        "includes": includes,
        "excludes": excludes,
        "include_files": include_files,
        "optimize": 2,
        "build_exe": BUILD_DIR,
    }

    base = "Win32GUI" if sys.platform == "win32" else None
    original_argv = sys.argv
    sys.argv = [sys.argv[0], "build"]

    try:
        setup(
            name=PROJECT_NAME,
            version=VERSION,
            description="Arknights Pass Material Maker",
            options={"build_exe": build_options},
            executables=[Executable(
                script=MAIN_SCRIPT,
                base=base,
                target_name=f"{PROJECT_NAME}.exe",
                icon=ICON_FILE if os.path.exists(ICON_FILE) else None,
            )],
        )
        license_file = os.path.join(BUILD_DIR, "frozen_application_license.txt")
        if os.path.exists(license_file):
            os.remove(license_file)
        return True
    except Exception as e:
        print(f"Build failed: {e}")
        return False
    finally:
        sys.argv = original_argv


def copy_class_icons():
    """复制职业图标到构建根目录"""
    print("Copying class icons...")
    src = os.path.join("resources", "class_icons")
    dst = os.path.join(BUILD_DIR, "class_icons")
    if os.path.exists(src):
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"  {src} -> {dst}")


def create_installer():
    """创建安装包"""
    print("\n" + "=" * 50)
    print("Creating installer...")
    print("=" * 50)

    iscc = find_inno_setup()
    if not iscc:
        iscc = download_inno_setup()
    if not iscc:
        print("Error: Inno Setup not available")
        return False

    if not os.path.exists(ISS_FILE):
        print(f"Error: {ISS_FILE} not found")
        return False

    os.makedirs(DIST_DIR, exist_ok=True)

    try:
        result = subprocess.run([iscc, ISS_FILE], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Inno Setup failed: {result.stderr}")
            return False

        print(result.stdout)
        for f in os.listdir(DIST_DIR):
            if f.endswith(".exe"):
                path = os.path.join(DIST_DIR, f)
                size = os.path.getsize(path) / 1024 / 1024
                print(f"\nCreated: {path} ({size:.2f} MB)")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    args = parse_args()

    print("=" * 50)
    print(f"  {PROJECT_NAME} Build Tool v{VERSION}")
    print("=" * 50)

    if not check_requirements():
        sys.exit(1)

    if args.clean:
        clean_build()

    print("\n" + "=" * 50)
    print("Running cx_Freeze...")
    print("=" * 50)

    if not run_cxfreeze(skip_flasher=args.skip_flasher):
        sys.exit(1)

    print(f"\ncx_Freeze done: {BUILD_DIR}/")
    copy_class_icons()

    if not args.no_installer:
        if create_installer():
            print("\n" + "=" * 50)
            print("Build completed!")
            print("=" * 50)
        else:
            print("\nInstaller skipped")


if __name__ == "__main__":
    main()
