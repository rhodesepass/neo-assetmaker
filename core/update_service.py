"""
更新服务 - GitHub Releases 自动更新（多线程多源支持）

本模块实现了多源并发更新检测和下载，解决单一源阻塞的问题。

## 当前实现的改进依据

### 问题：urllib.request.urlopen 是同步阻塞调用
官方文档: https://docs.python.org/3/library/urllib.request.html
> "Open *url*... This function always returns an object which can work as a context manager..."
urlopen() 会阻塞整个线程直到网络响应返回。

### 解决方案：使用 concurrent.futures.ThreadPoolExecutor
官方文档: https://docs.python.org/3/library/concurrent.futures.html
> "The ThreadPoolExecutor class is an Executor subclass that uses a pool of threads
>  to execute calls asynchronously."
>
> "as_completed(fs, timeout=None): Returns an iterator over the Future instances...
>  that yields futures as they complete (finished or cancelled)."

关键优势：
1. submit() 提交任务立即返回 Future，不阻塞
2. as_completed() 按完成顺序返回结果 → 实现竞速策略
3. Future.result(timeout=...) 支持超时控制

### 多源策略
- 竞速策略 (Race)：同时请求所有源，取最快成功的结果 → 用于更新检测
- 故障转移策略 (Failover)：按优先级依次尝试 → 用于文件下载
"""
import os
import re
import json
import logging
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from typing import Optional, Tuple, List, Dict, Callable, TypeVar, Generic
from dataclasses import dataclass
from urllib.request import urlopen, Request

from PyQt6.QtCore import QThread, pyqtSignal, QObject

from config.constants import (
    GITHUB_OWNER, GITHUB_REPO,
    UpdateSource, UPDATE_API_SOURCES, DOWNLOAD_SOURCES
)

logger = logging.getLogger(__name__)

# GitHub API Configuration
GITHUB_API_BASE = "https://api.github.com"
USER_AGENT = "ArknightsPassMaker-Updater/1.0"

T = TypeVar('T')


@dataclass
class ReleaseInfo:
    """Release information from GitHub"""
    version: str           # e.g., "1.0.5"
    tag_name: str          # e.g., "v1.0.5"
    name: str              # Release title
    body: str              # Changelog/description (markdown)
    published_at: str      # ISO timestamp
    download_url: str      # Direct download URL for .exe installer
    download_size: int     # File size in bytes
    html_url: str          # Web URL to release page


@dataclass
class SourceResult(Generic[T]):
    """
    多源请求的结果封装

    泛型参数 T 表示成功时返回的数据类型（如 ReleaseInfo 或文件路径）
    """
    source_name: str               # 成功的源名称
    success: bool                  # 是否成功
    data: Optional[T] = None       # 成功时的数据
    error: Optional[str] = None    # 失败时的错误信息
    response_time: float = 0.0     # 响应时间（秒）


class VersionComparer:
    """Version comparison utilities"""

    @staticmethod
    def parse_version(version_str: str) -> Tuple[int, ...]:
        """Parse version string to tuple of integers.

        Args:
            version_str: Version like "1.0.4" or "v1.0.4"

        Returns:
            Tuple of integers, e.g., (1, 0, 4)
        """
        # Remove 'v' prefix if present
        version_str = version_str.lstrip('vV')
        # Extract only numeric parts
        parts = re.findall(r'\d+', version_str)
        return tuple(int(p) for p in parts)

    @staticmethod
    def is_newer(remote_version: str, local_version: str) -> bool:
        """Check if remote version is newer than local.

        Args:
            remote_version: Version from GitHub release
            local_version: Current application version

        Returns:
            True if remote is newer
        """
        try:
            remote = VersionComparer.parse_version(remote_version)
            local = VersionComparer.parse_version(local_version)
            return remote > local
        except (ValueError, IndexError):
            return False


class MultiSourceRequestManager:
    """
    多源请求管理器 - 支持竞速和故障转移策略

    实现依据: https://docs.python.org/3/library/concurrent.futures.html

    竞速策略 (race_request):
        同时向所有源发起请求，使用 as_completed() 按完成顺序处理，
        返回第一个成功的结果，并取消其余请求。

    故障转移策略 (failover_request):
        按优先级顺序依次尝试各源，直到成功或全部失败。
    """

    def __init__(self, max_workers: int = 5):
        """
        初始化请求管理器

        Args:
            max_workers: 线程池最大线程数
        """
        self._executor: Optional[ThreadPoolExecutor] = None
        self._max_workers = max_workers
        self._cancelled = threading.Event()

    def _ensure_executor(self):
        """确保线程池已创建"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers)

    def cancel(self):
        """取消所有进行中的请求"""
        self._cancelled.set()

    def reset(self):
        """重置取消状态"""
        self._cancelled.clear()

    def race_request(
        self,
        sources: List[UpdateSource],
        request_func: Callable[[UpdateSource], T],
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> SourceResult[T]:
        """
        竞速策略：同时请求所有源，返回最快成功的结果

        根据 concurrent.futures 官方文档:
        "as_completed() returns an iterator over the Future instances...
        that yields futures as they complete (finished or cancelled)"

        Args:
            sources: 更新源列表
            request_func: 执行请求的函数，接收 UpdateSource 参数
            progress_callback: 可选的进度回调函数

        Returns:
            SourceResult 包含第一个成功源的数据，或错误信息
        """
        enabled_sources = [s for s in sources if s.enabled]
        if not enabled_sources:
            return SourceResult(source_name="", success=False, error="没有可用的更新源")

        self.reset()
        self._ensure_executor()
        futures: Dict[Future, UpdateSource] = {}

        # 同时提交所有请求
        for source in enabled_sources:
            if progress_callback:
                progress_callback(f"正在尝试 {source.name}...")
            future = self._executor.submit(self._execute_request, source, request_func)
            futures[future] = source

        # 按完成顺序处理结果
        for future in as_completed(futures.keys()):
            if self._cancelled.is_set():
                # 取消剩余请求
                for f in futures.keys():
                    f.cancel()
                return SourceResult(source_name="", success=False, error="已取消")

            source = futures[future]
            try:
                result = future.result(timeout=source.timeout)
                if result.success:
                    # 成功！取消剩余请求
                    for f in futures.keys():
                        if f != future:
                            f.cancel()
                    if progress_callback:
                        progress_callback(f"通过 {source.name} 连接成功")
                    return result
                else:
                    logger.debug(f"源 {source.name} 返回失败: {result.error}")
            except Exception as e:
                logger.debug(f"源 {source.name} 请求异常: {e}")
                continue

        return SourceResult(source_name="", success=False, error="所有更新源均无法访问")

    def failover_request(
        self,
        sources: List[UpdateSource],
        request_func: Callable[[UpdateSource], T],
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> SourceResult[T]:
        """
        故障转移策略：按优先级依次尝试各源

        Args:
            sources: 更新源列表（将按 priority 排序）
            request_func: 执行请求的函数
            progress_callback: 可选的进度回调函数

        Returns:
            SourceResult 包含第一个成功源的数据，或错误信息
        """
        enabled_sources = [s for s in sources if s.enabled]
        sorted_sources = sorted(enabled_sources, key=lambda s: s.priority)
        last_error = "没有可用的更新源"

        for source in sorted_sources:
            if self._cancelled.is_set():
                return SourceResult(source_name="", success=False, error="已取消")

            if progress_callback:
                progress_callback(f"正在尝试 {source.name}...")

            try:
                result = self._execute_request(source, request_func)
                if result.success:
                    if progress_callback:
                        progress_callback(f"通过 {source.name} 连接成功")
                    return result
                else:
                    last_error = result.error or f"{source.name} 请求失败"
                    logger.debug(f"源 {source.name} 失败: {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.debug(f"源 {source.name} 异常: {e}")
                continue

        return SourceResult(source_name="", success=False, error=last_error)

    def _execute_request(
        self,
        source: UpdateSource,
        request_func: Callable[[UpdateSource], T]
    ) -> SourceResult[T]:
        """执行单个请求并封装结果"""
        start_time = time.time()

        try:
            data = request_func(source)
            response_time = time.time() - start_time
            return SourceResult(
                source_name=source.name,
                success=True,
                data=data,
                response_time=response_time
            )
        except Exception as e:
            response_time = time.time() - start_time
            return SourceResult(
                source_name=source.name,
                success=False,
                error=str(e),
                response_time=response_time
            )

    def shutdown(self):
        """关闭线程池"""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None


class UpdateCheckWorker(QThread):
    """
    后台更新检查工作线程（多源竞速策略）

    使用 ThreadPoolExecutor 同时请求所有配置的源，
    取最快成功返回的结果，实现最低延迟的更新检测。
    """

    check_completed = pyqtSignal(object)  # ReleaseInfo or None
    check_failed = pyqtSignal(str)        # Error message
    check_progress = pyqtSignal(str)      # Progress message (显示当前尝试的源)

    def __init__(
        self,
        current_version: str,
        sources: Optional[List[UpdateSource]] = None,
        parent=None
    ):
        super().__init__(parent)
        self._current_version = current_version
        self._sources = sources or UPDATE_API_SOURCES
        self._request_manager = MultiSourceRequestManager(max_workers=len(self._sources))

    def run(self):
        """使用竞速策略从多个源检查更新"""
        try:
            result = self._request_manager.race_request(
                sources=self._sources,
                request_func=self._fetch_from_source,
                progress_callback=lambda msg: self.check_progress.emit(msg)
            )

            if not result.success:
                self.check_failed.emit(result.error or "所有源均无法访问")
                return

            release_info = result.data

            # 检查是否是更新版本
            if not VersionComparer.is_newer(release_info.version, self._current_version):
                self.check_completed.emit(None)  # 已是最新版本
                return

            self.check_completed.emit(release_info)

        except Exception as e:
            logger.exception("检查更新时发生错误")
            self.check_failed.emit(f"检查更新失败: {str(e)}")
        finally:
            self._request_manager.shutdown()

    def _fetch_from_source(self, source: UpdateSource) -> ReleaseInfo:
        """从指定源获取版本信息"""
        url = source.url_template.format(owner=GITHUB_OWNER, repo=GITHUB_REPO)

        request = Request(url)
        request.add_header('User-Agent', USER_AGENT)
        request.add_header('Accept', 'application/vnd.github.v3+json')

        with urlopen(request, timeout=source.timeout) as response:
            data = json.loads(response.read().decode('utf-8'))

        return self._parse_release_data(data)

    def _parse_release_data(self, data: dict) -> ReleaseInfo:
        """解析 GitHub API 响应"""
        tag_name = data.get('tag_name', '')
        version = tag_name.lstrip('vV')

        # 查找 Windows 安装包
        download_url = None
        download_size = 0

        for asset in data.get('assets', []):
            name = asset.get('name', '')
            if name.endswith('_Setup.exe') or name.endswith('.exe'):
                download_url = asset.get('browser_download_url')
                download_size = asset.get('size', 0)
                break

        if not download_url:
            raise ValueError("未找到Windows安装包")

        return ReleaseInfo(
            version=version,
            tag_name=tag_name,
            name=data.get('name', f'v{version}'),
            body=data.get('body', ''),
            published_at=data.get('published_at', ''),
            download_url=download_url,
            download_size=download_size,
            html_url=data.get('html_url', '')
        )


class UpdateDownloadWorker(QThread):
    """
    后台下载工作线程（多源故障转移策略）

    按优先级依次尝试各下载源，适合大文件下载，
    避免竞速策略带来的带宽浪费。
    """

    progress_updated = pyqtSignal(int, str)   # (percentage, message)
    download_completed = pyqtSignal(str)       # Downloaded file path
    download_failed = pyqtSignal(str)          # Error message

    def __init__(
        self,
        release_info: ReleaseInfo,
        sources: Optional[List[UpdateSource]] = None,
        parent=None
    ):
        super().__init__(parent)
        self._release_info = release_info
        self._sources = sources or DOWNLOAD_SOURCES
        self._cancelled = threading.Event()
        self._request_manager = MultiSourceRequestManager(max_workers=1)
        self._current_source_name = ""

    def cancel(self):
        """取消下载"""
        self._cancelled.set()
        self._request_manager.cancel()

    def run(self):
        """使用故障转移策略下载安装包"""
        try:
            # 构建下载源 URL
            download_sources = self._build_download_sources()

            result = self._request_manager.failover_request(
                sources=download_sources,
                request_func=self._download_from_source,
                progress_callback=lambda msg: self.progress_updated.emit(0, msg)
            )

            if not result.success:
                self.download_failed.emit(result.error or "所有下载源均失败")
                return

            self.progress_updated.emit(100, "下载完成")
            self.download_completed.emit(result.data)

        except Exception as e:
            logger.exception("下载更新时发生错误")
            self.download_failed.emit(f"下载失败: {str(e)}")
        finally:
            self._request_manager.shutdown()

    def _build_download_sources(self) -> List[UpdateSource]:
        """根据原始下载 URL 构建多源下载地址"""
        original_url = self._release_info.download_url
        sources = []

        for src in self._sources:
            if not src.enabled:
                continue

            # 替换 {direct_url} 占位符
            url = src.url_template.replace('{direct_url}', original_url)

            sources.append(UpdateSource(
                name=src.name,
                url_template=url,
                source_type=src.source_type,
                priority=src.priority,
                timeout=src.timeout,
                enabled=True
            ))

        return sources

    def _download_from_source(self, source: UpdateSource) -> str:
        """从指定源下载文件"""
        url = source.url_template
        total_size = self._release_info.download_size

        # 准备输出文件
        temp_dir = tempfile.gettempdir()
        filename = f"ArknightsPassMaker_v{self._release_info.version}_Setup.exe"
        output_path = os.path.join(temp_dir, filename)

        self._current_source_name = source.name

        request = Request(url)
        request.add_header('User-Agent', USER_AGENT)

        self.progress_updated.emit(0, f"正在从 {source.name} 下载...")

        try:
            with urlopen(request, timeout=source.timeout) as response:
                downloaded = 0
                chunk_size = 8192  # 8KB chunks

                with open(output_path, 'wb') as f:
                    while True:
                        if self._cancelled.is_set():
                            f.close()
                            if os.path.exists(output_path):
                                os.remove(output_path)
                            raise InterruptedError("下载已取消")

                        chunk = response.read(chunk_size)
                        if not chunk:
                            break

                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            size_mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            msg = f"[{source.name}] 已下载 {size_mb:.1f} / {total_mb:.1f} MB"
                        else:
                            percent = 50  # Unknown size
                            size_mb = downloaded / (1024 * 1024)
                            msg = f"[{source.name}] 已下载 {size_mb:.1f} MB"

                        self.progress_updated.emit(percent, msg)

            return output_path

        except Exception as e:
            # 清理部分下载的文件
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
            raise


class UpdateService(QObject):
    """
    更新服务 - 管理更新检查和下载

    信号接口保持向后兼容，新增 check_progress 信号用于显示多源切换状态。
    """

    # UI 通信信号
    check_started = pyqtSignal()
    check_completed = pyqtSignal(object)  # ReleaseInfo or None
    check_failed = pyqtSignal(str)
    check_progress = pyqtSignal(str)      # 新增：显示当前尝试的源

    download_started = pyqtSignal()
    download_progress = pyqtSignal(int, str)
    download_completed = pyqtSignal(str)  # File path
    download_failed = pyqtSignal(str)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self._current_version = current_version
        self._check_worker: Optional[UpdateCheckWorker] = None
        self._download_worker: Optional[UpdateDownloadWorker] = None
        self._latest_release: Optional[ReleaseInfo] = None

    @property
    def is_checking(self) -> bool:
        return self._check_worker is not None and self._check_worker.isRunning()

    @property
    def is_downloading(self) -> bool:
        return self._download_worker is not None and self._download_worker.isRunning()

    @property
    def latest_release(self) -> Optional[ReleaseInfo]:
        return self._latest_release

    def check_for_updates(self):
        """开始后台检查更新（多源竞速策略）"""
        if self.is_checking:
            return

        self._check_worker = UpdateCheckWorker(self._current_version, parent=self)
        self._check_worker.check_completed.connect(self._on_check_completed)
        self._check_worker.check_failed.connect(self._on_check_failed)
        self._check_worker.check_progress.connect(self.check_progress.emit)

        self.check_started.emit()
        self._check_worker.start()

    def download_update(self, release_info: ReleaseInfo = None):
        """开始下载更新（多源故障转移策略）"""
        if self.is_downloading:
            return

        release = release_info or self._latest_release
        if not release:
            self.download_failed.emit("没有可下载的更新")
            return

        self._download_worker = UpdateDownloadWorker(release, parent=self)
        self._download_worker.progress_updated.connect(self.download_progress.emit)
        self._download_worker.download_completed.connect(self._on_download_completed)
        self._download_worker.download_failed.connect(self._on_download_failed)

        self.download_started.emit()
        self._download_worker.start()

    def cancel_download(self):
        """取消正在进行的下载"""
        if self._download_worker and self._download_worker.isRunning():
            self._download_worker.cancel()

    def _on_check_completed(self, release_info: Optional[ReleaseInfo]):
        self._latest_release = release_info
        self.check_completed.emit(release_info)
        self._cleanup_check_worker()

    def _on_check_failed(self, error_msg: str):
        self.check_failed.emit(error_msg)
        self._cleanup_check_worker()

    def _on_download_completed(self, file_path: str):
        self.download_completed.emit(file_path)
        self._cleanup_download_worker()

    def _on_download_failed(self, error_msg: str):
        self.download_failed.emit(error_msg)
        self._cleanup_download_worker()

    def _cleanup_check_worker(self):
        if self._check_worker:
            self._check_worker.deleteLater()
            self._check_worker = None

    def _cleanup_download_worker(self):
        if self._download_worker:
            self._download_worker.deleteLater()
            self._download_worker = None
