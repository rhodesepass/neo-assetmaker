"""
明日方舟通行证素材工具箱 - cx_Freeze + Inno Setup 打包工具
"""
import os
import sys
import subprocess
import argparse
import shutil
import urllib.request
sys.setrecursionlimit(10000)

PROJECT_NAME = "ArknightsPassMaker"
MAIN_SCRIPT = "main.py"
ICON_FILE = "resources/icons/favicon.ico"


def get_version() -> str:
    """从 pyproject.toml 读取版本号（单一来源）

    参考: cx_Freeze 在 _pyproject.py:7-10 使用相同的 tomllib/tomli fallback 模式
    """
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyproject.toml"), "rb") as f:
        return tomllib.load(f)["project"]["version"]


VERSION = get_version()
BUILD_DIR = PROJECT_NAME
DIST_DIR = "dist"
ISS_FILE = "installer.iss"
INNO_SETUP_DIR = "tools/innosetup"


def parse_args():
    parser = argparse.ArgumentParser(description=f"{PROJECT_NAME} Build Tool")
    parser.add_argument('--no-installer', action='store_true', help='Skip installer packaging')
    parser.add_argument('--clean', action='store_true', help='Clean build directories')
    parser.add_argument('--skip-flasher', action='store_true', help='Skip epass_flasher/bin check (not recommended)')
    return parser.parse_args()


def get_site_packages():
    """获取 site-packages 路径（跨平台）

    参考: https://docs.python.org/3/library/sysconfig.html#sysconfig.get_path
    """
    import sysconfig
    return sysconfig.get_path('purelib')


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




def _clean_pycache(base_dir='.'):
    """清理项目源码的 __pycache__ 目录

    跳过 .venv/ 等无关目录（避免删除第三方包字节码）
    """
    skip_dirs = {'.venv', 'venv', '.git', 'simulator', 'node_modules', BUILD_DIR, DIST_DIR}
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        if '__pycache__' in dirs:
            cache_path = os.path.join(root, '__pycache__')
            shutil.rmtree(cache_path)
            print(f"  Cleared: {cache_path}")
            dirs.remove('__pycache__')


def _diagnose_build_env():
    """打印构建环境诊断信息，便于 CI 调试"""
    import importlib.util
    import sysconfig as _sc

    print("\n--- Build Environment ---")
    print(f"  Python: {sys.version}")
    print(f"  Platform: {sys.platform}")
    print(f"  Executable: {sys.executable}")
    print(f"  purelib: {_sc.get_path('purelib')}")
    print(f"  platlib: {_sc.get_path('platlib')}")
    print(f"  sys.path ({len(sys.path)} entries):")
    for i, p in enumerate(sys.path):
        print(f"    [{i}] {p}")
    # 关键包定位
    for pkg in ("OpenGL", "av", "cv2", "PyQt6", "cx_Freeze", "numpy"):
        spec = importlib.util.find_spec(pkg)
        status = spec.origin if spec else "NOT FOUND"
        print(f"  {pkg}: {status}")
    print("--- End ---\n")


def _verify_modules(search_paths, project_root):
    """统一验证所有关键模块可被 PathFinder 发现

    cx_Freeze finder.py:382-383 使用 importlib.machinery.PathFinder.find_spec(name, path)
    而非 importlib.util.find_spec（后者使用 sys.meta_path hooks，结果可能不同）。
    本函数同时检查本地项目模块和第三方包，并在 PathFinder 失败时使用
    importlib.util.find_spec 作为 fallback 定位包路径。
    """
    import importlib.machinery
    import importlib.util as _ilu

    # ── 本地项目模块检查 ──
    gui_path = os.path.join(project_root, "gui")
    local_modules = [
        ("gui", [project_root]),
        ("gui.main_window", [gui_path]),
        ("core", [project_root]),
        ("config", [project_root]),
    ]
    for mod_name, mod_path in local_modules:
        importlib.machinery.PathFinder.invalidate_caches()
        spec = importlib.machinery.PathFinder.find_spec(mod_name, mod_path)
        if spec is None:
            print(f"  FATAL: PathFinder cannot find {mod_name} in {mod_path}")
            print(f"  Directory listing: {os.listdir(mod_path[0])}")
            return False
        print(f"  PathFinder check: {mod_name} -> {spec.origin}")

    # ── 第三方包检查（含 fallback 路径发现）──
    # importlib.util.find_spec 使用完整的 sys.meta_path（包括 uv 的自定义 finder）
    # PathFinder.find_spec 只搜索给定的 path 列表
    pip_names = {"OpenGL": "PyOpenGL", "cv2": "opencv-python"}
    critical_packages = ["OpenGL", "av", "cv2", "PyQt6"]
    missing = []

    for pkg_name in critical_packages:
        importlib.machinery.PathFinder.invalidate_caches()
        pf_spec = importlib.machinery.PathFinder.find_spec(pkg_name, search_paths)
        if pf_spec:
            print(f"  PathFinder check: {pkg_name} -> {pf_spec.origin}")
            continue

        # fallback: 使用 importlib.util.find_spec 定位并添加路径
        util_spec = _ilu.find_spec(pkg_name)
        if util_spec is None:
            pip_name = pip_names.get(pkg_name, pkg_name)
            print(f"  FATAL: {pkg_name} is NOT INSTALLED")
            print(f"         Run: uv pip install {pip_name}")
            missing.append(pkg_name)
            continue

        # 从 util_spec 提取父目录添加到搜索路径
        parent = None
        if util_spec.submodule_search_locations:
            parent = os.path.dirname(util_spec.submodule_search_locations[0])
        elif util_spec.origin:
            parent = os.path.dirname(os.path.dirname(util_spec.origin))
        if parent and parent not in search_paths:
            search_paths.insert(1, parent)
            print(f"  Fallback: added {parent} for {pkg_name}")
        print(f"  WARNING: PathFinder cannot find {pkg_name}, "
              f"but importlib.util found it at {util_spec.origin}")

    if missing:
        print(f"\n  Cannot proceed without: {', '.join(missing)}")
        print(f"  This usually means 'uv sync' did not install these packages.")
        return False

    return True


def check_requirements():
    """检查构建环境"""
    print("Checking build environment...")

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

    print("Cleaning __pycache__ directories...")
    _clean_pycache()


def run_cxfreeze(skip_flasher=False):
    """执行 cx_Freeze 打包"""

    # 确保项目根目录在 Python 路径中（防御性措施，正常应通过 uv sync --group dev 的 editable install 实现）
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    print(f"Project root: {project_root}")

    # 输出构建环境诊断信息
    _diagnose_build_env()

    # ── 构建 cx_Freeze 模块搜索路径 ──
    # cx_Freeze 只使用 PathFinder（finder.py:382-383），不使用 sys.meta_path。
    # 必须显式包含 site-packages，否则 uv/conda 等环境中第三方包可能找不到。
    import sysconfig as _sc
    search_paths = [project_root] + list(sys.path)
    for extra in [_sc.get_path('purelib'), _sc.get_path('platlib')]:
        if extra and os.path.isdir(extra) and extra not in search_paths:
            search_paths.insert(1, extra)
            print(f"  Added site-packages to search path: {extra}")

    # 统一验证本地模块和第三方包
    if not _verify_modules(search_paths, project_root):
        return False

    # 预编译检查：使用与 cx_Freeze 相同的 optimize 级别（finder.py:446-448）
    main_window_path = os.path.join(project_root, "gui", "main_window.py")
    try:
        with open(main_window_path, "rb") as f:
            compile(f.read(), main_window_path, "exec", optimize=2)
        print(f"  Compile check: gui/main_window.py (optimize=2) OK")
    except SyntaxError as e:
        print(f"  FATAL: gui/main_window.py compile error: {e}")
        return False

    # 清理 __pycache__，确保使用最新源代码编译
    print("Clearing __pycache__ before build...")
    _clean_pycache()

    os.environ["QT_API"] = "pyqt6"

    from cx_Freeze import setup, Executable

    site_packages = get_site_packages()

    packages = [
        "PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets",
        "PyQt6.QtOpenGLWidgets", "PyQt6.QtOpenGL",
        "qfluentwidgets",
        # av (PyAV) 不放在 packages 中 — cx_Freeze 7.2.10 的 PathFinder.find_spec
        # 无法定位 PyAV 17+ 的 abi3 C 扩展包（finder.py:383 返回 None）。
        # 改为通过 include_files 手动复制 av/ 和 av.libs/ 目录。
        # PyOpenGL 不放在 packages 中 — packages 会触发 cx_Freeze 的
        # _import_all_sub_modules() 递归扫描整个 OpenGL/ 目录(2800+ 文件),
        # 任何子模块加载失败都会导致 ImportError 中止构建。
        # 改为在 includes 中精确指定入口点和动态加载的模块。
        "cv2", "PIL", "numpy", "jsonschema", "thefuzz",
        "logging", "json", "uuid", "dataclasses",
        "httpx", "httpcore", "httpx._transports",
        "keyring", "keyring.backends",
        "platformdirs",
        "fido2", "fido2.hid", "fido2.client", "fido2.webauthn",
        "usb", "usb.core", "usb.backend", "usb.backend.libusb1",
        # 本地项目包 — 使用 packages 让 cx_Freeze 通过 _import_all_sub_modules 自动发现所有子模块
        "gui", "core", "config", "utils", "_mext",
    ]

    includes = [
        # ── PyOpenGL: 精确包含，避免 packages 递归发现导致构建失败 ──
        # 入口点 — cx_Freeze 自动跟踪 GL/__init__.py 中的 star-import 链
        # (GL.VERSION.GL_1_1~GL_4_6, GL.pointers, GL.images, GL.exceptional,
        #  GL.glget, GL.vboimplementation, raw.GL.VERSION.* 等所有静态依赖)
        "OpenGL",
        "OpenGL.GL",
        # 平台模块 — PlatformPlugin 使用 importByName() 动态加载，
        # cx_Freeze 静态分析无法跟踪 __import__ 中的字符串参数
        "OpenGL.platform.win32",
        "OpenGL.platform.ctypesloader",
        "OpenGL.platform.baseplatform",
        "OpenGL._configflags",
        "OpenGL.plugins",
        # 数组格式处理器 — FormatHandler 插件使用 __import__ 动态加载
        "OpenGL.arrays.numpymodule",
        "OpenGL.arrays.ctypesarrays",
        "OpenGL.arrays.ctypesparameters",
        "OpenGL.arrays.ctypespointers",
        "OpenGL.arrays.lists",
        "OpenGL.arrays.nones",
        "OpenGL.arrays.numbers",
        "OpenGL.arrays.strings",
        "OpenGL.arrays.buffers",
        "OpenGL.arrays.arraydatatype",
        "OpenGL.arrays.formathandler",
        "OpenGL.converters",
        # raw GL 绑定
        "OpenGL.raw.GL",
    ]

    excludes = [
        "tkinter", "unittest", "test", "tests", "pytest", "IPython",
        "notebook", "jupyter", "torch.testing", "torch.utils.tensorboard",
        "torch.utils.benchmark", "torch.distributed", "torchvision",
        "torchaudio", "scipy.spatial.cKDTree", "sympy",
        "PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
        # OpenGL: 排除非 Windows 平台模块（finder.py:230 会跳过 excludes 中的模块）
        "OpenGL.platform.glx",
        "OpenGL.platform.darwin",
        "OpenGL.platform.egl",
        "OpenGL.platform.osmesa",
        "OpenGL.platform.entrypoint31",
        # OpenGL: 排除不需要的子包（减小体积，防止间接引用报错）
        "OpenGL.GLES1", "OpenGL.GLES2", "OpenGL.GLES3",
        "OpenGL.GLU", "OpenGL.GLUT", "OpenGL.GLE",
        "OpenGL.EGL", "OpenGL.GLX", "OpenGL.WGL",
        "OpenGL.AGL", "OpenGL.Tk",
    ]

    include_files = [
        ("resources", "resources"),
        ("resources/class_icons", "class_icons"),  # 运行时通过 class_icons/ 相对路径访问
    ]
    if os.path.exists("ffmpeg.exe"):
        include_files.append(("ffmpeg.exe", "ffmpeg.exe"))
    if os.path.exists("ffprobe.exe"):
        include_files.append(("ffprobe.exe", "ffprobe.exe"))

    # av (PyAV): 手动包含，绕过 cx_Freeze PathFinder（参见 packages 列表中的注释）
    # include_files 在 freezer.py:117 process_path_specs 中处理，直接复制目录，
    # 不经过 PathFinder.find_spec，冻结应用的 lib/ 目录在运行时会被加入 sys.path。
    av_pkg_dir = os.path.join(site_packages, "av")
    if os.path.isdir(av_pkg_dir):
        include_files.append((av_pkg_dir, "lib/av"))
        print(f"  Including av package: {av_pkg_dir}")
    else:
        print(f"  WARNING: av package not found at {av_pkg_dir}")
    # av.libs 包含 FFmpeg DLL（Windows delvewheel 打包，cx_Freeze hooks/av.py:26 原本处理）
    av_libs_dir = os.path.join(site_packages, "av.libs")
    if os.path.isdir(av_libs_dir):
        include_files.append((av_libs_dir, "lib/av.libs"))
        print(f"  Including av.libs: {av_libs_dir}")

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

    # 添加烧录工具 bin 目录（flasher_dialog 直接调用的工具）
    flasher_bin_dir = os.path.join("epass_flasher", "bin")
    if os.path.exists(flasher_bin_dir):
        include_files.append((flasher_bin_dir, os.path.join("epass_flasher", "bin")))
        print(f"  Including flasher bin dir: {flasher_bin_dir}")
    elif not skip_flasher:
        print("\nERROR: epass_flasher/bin/ not found, aborting")
        print("       Use --skip-flasher to skip this check (not recommended)")
        return False
    else:
        print("  Warning: epass_flasher/bin/ not found (skipped due to --skip-flasher)")

    pyqt6_plugins = os.path.join(site_packages, "PyQt6", "Qt6", "plugins")
    if os.path.exists(pyqt6_plugins):
        for plugin in ["platforms", "imageformats", "styles"]:
            plugin_path = os.path.join(pyqt6_plugins, plugin)
            if os.path.exists(plugin_path):
                include_files.append((plugin_path, f"lib/PyQt6/Qt6/plugins/{plugin}"))

    # libusb DLL（pyusb/fido2 运行时依赖）
    libusb_dll = os.path.join(site_packages, "fido2", "libusb-1.0.dll")
    if os.path.exists(libusb_dll):
        include_files.append((libusb_dll, "libusb-1.0.dll"))
        print(f"  Including libusb: {libusb_dll}")

    build_options = {
        "packages": packages,
        "includes": includes,
        "excludes": excludes,
        "include_files": include_files,
        "optimize": 2,
        "build_exe": BUILD_DIR,
        "path": search_paths,
    }

    # Windows 上使用 "gui" base 避免出现控制台窗口（cx_Freeze 7.0+ 用 "gui" 替代了旧的 "Win32GUI"）
    base = "gui" if sys.platform == "win32" else None

    print(f"\n  Version: {VERSION}")
    print(f"  Packages ({len(packages)}): {', '.join(packages)}")
    print(f"  Include files ({len(include_files)}):")
    for src, dst in include_files:
        print(f"    {src} -> {dst}")

    # 使用 script_args 替代 sys.argv hack（参考 cx_Freeze cli.py:251 使用相同方式）
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
            script_args=["build"],
        )
        license_file = os.path.join(BUILD_DIR, "frozen_application_license.txt")
        if os.path.exists(license_file):
            os.remove(license_file)
        return True
    except Exception as e:
        import traceback
        print(f"\nBuild failed: {e}")
        traceback.print_exc()
        print(f"\nSearch paths ({len(search_paths)}):")
        for i, p in enumerate(search_paths):
            print(f"  [{i}] {p}")
        return False


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
        result = subprocess.run(
            [iscc, f"/DMyAppVersion={VERSION}", ISS_FILE],
            capture_output=True, text=True,
        )
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

    if not args.no_installer:
        if create_installer():
            print("\n" + "=" * 50)
            print("Build completed!")
            print("=" * 50)
        else:
            print("\nInstaller skipped")


if __name__ == "__main__":
    main()
