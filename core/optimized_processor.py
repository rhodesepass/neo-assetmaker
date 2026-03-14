"""
优化的视频处理器 - 支持多线程、缓存、流式处理
使用 PyAV 进行视频解码，替代 cv2.VideoCapture
"""
import os
import cv2
import numpy as np
from typing import Optional, Callable, List, Tuple
from concurrent.futures import ThreadPoolExecutor, Future
from functools import lru_cache
from threading import Lock
import logging

# PyAV 用于视频解码，替代 cv2.VideoCapture
try:
    import av
    HAS_AV = True
except ImportError:
    HAS_AV = False

logger = logging.getLogger(__name__)


class OptimizedVideoProcessor:
    """优化的视频处理器"""

    def __init__(self, max_workers: int = 4, cache_size: int = 32):
        self.max_workers = max_workers
        self.cache_size = cache_size
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = Lock()
        self._cache = {}
        self._cache_order = []

    @lru_cache(maxsize=32)
    def process_frame(self, frame_path: str, timestamp: float) -> Optional[np.ndarray]:
        """
        处理单帧（带缓存）

        参数:
            frame_path: 帧文件路径
            timestamp: 时间戳

        返回:
            处理后的帧（numpy数组）
        """
        try:
            frame = cv2.imread(frame_path)
            if frame is None:
                logger.warning(f"无法读取帧: {frame_path}")
                return None

            # 这里可以添加帧处理逻辑
            # 例如：调整大小、应用滤镜等

            return frame
        except Exception as e:
            logger.error(f"处理帧失败: {e}")
            return None

    def process_video_async(
        self,
        video_path: str,
        callback: Callable[[List[np.ndarray]], None],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Future:
        """
        异步处理视频

        参数:
            video_path: 视频文件路径
            callback: 处理完成回调函数
            progress_callback: 进度回调函数 (current, total)

        返回:
            Future对象
        """
        def process():
            try:
                # 使用 PyAV 解码视频
                container = av.open(video_path)
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"  # 启用多线程解码

                # 从 stream 元数据获取总帧数
                total_frames = stream.frames if stream.frames else 0
                frames = []

                for av_frame in container.decode(stream):
                    # 转换为 BGR numpy 数组（与 cv2 兼容）
                    frame = av_frame.to_ndarray(format='bgr24')
                    frames.append(frame)

                    # 进度回调
                    if progress_callback:
                        progress_callback(len(frames), total_frames)

                container.close()
                callback(frames)

            except Exception as e:
                logger.error(f"处理视频失败: {e}")
                callback([])

        return self.executor.submit(process)

    def extract_frames(
        self,
        video_path: str,
        frame_indices: List[int],
        callback: Callable[[List[Tuple[int, np.ndarray]]], None]
    ) -> Future:
        """
        提取指定帧（并行处理）

        参数:
            video_path: 视频文件路径
            frame_indices: 要提取的帧索引列表
            callback: 完成回调函数

        返回:
            Future对象
        """
        def extract_single_frame(index: int) -> Tuple[int, Optional[np.ndarray]]:
            """使用 PyAV seek + decode 提取单帧，避免每次创建新容器"""
            try:
                container = av.open(video_path)
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"

                # 精确 seek 到目标帧
                fps = float(stream.average_rate) if stream.average_rate else 30.0
                time_base = stream.time_base

                if time_base and fps > 0:
                    target_sec = index / fps
                    target_pts = int(target_sec / time_base)
                    container.seek(target_pts, stream=stream, backward=True)

                # 解码并跳过到目标帧
                frame = None
                for av_frame in container.decode(stream):
                    if av_frame.pts is not None and time_base and fps > 0:
                        current_sec = float(av_frame.pts * time_base)
                        current_idx = int(current_sec * fps)
                    else:
                        current_idx = 0

                    if current_idx >= index:
                        frame = av_frame.to_ndarray(format='bgr24')
                        break

                container.close()

                if frame is not None:
                    return (index, frame)
                else:
                    return (index, None)
            except Exception as e:
                logger.error(f"提取帧失败 (index={index}): {e}")
                return (index, None)

        def process():
            results = []
            futures = []

            # 并行提取帧
            for index in frame_indices:
                future = self.executor.submit(extract_single_frame, index)
                futures.append(future)

            # 等待所有任务完成
            for future in futures:
                result = future.result()
                results.append(result)

            callback(results)

        return self.executor.submit(process)

    def process_video_stream(
        self,
        video_path: str,
        frame_processor: Callable[[np.ndarray], np.ndarray],
        output_path: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ):
        """
        流式处理视频（逐帧处理，内存友好）

        参数:
            video_path: 输入视频路径
            frame_processor: 帧处理函数
            output_path: 输出视频路径（可选）
            progress_callback: 进度回调函数
        """
        try:
            # 使用 PyAV 解码视频
            container = av.open(video_path)
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"  # 启用多线程解码

            # 从 stream 元数据获取视频属性
            fps = float(stream.average_rate) if stream.average_rate else 30.0
            width = stream.width
            height = stream.height
            total_frames = stream.frames if stream.frames else 0

            # 创建视频写入器（仍使用 cv2.VideoWriter）
            writer = None
            if output_path:
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

            frame_count = 0

            for av_frame in container.decode(stream):
                # 转换为 BGR numpy 数组
                frame = av_frame.to_ndarray(format='bgr24')

                # 处理帧
                processed_frame = frame_processor(frame)

                # 写入输出
                if writer:
                    writer.write(processed_frame)

                frame_count += 1

                # 进度回调
                if progress_callback and frame_count % 10 == 0:
                    progress_callback(frame_count, total_frames)

            # 清理
            container.close()
            if writer:
                writer.release()

            logger.info(f"视频处理完成: {video_path}")

        except Exception as e:
            logger.error(f"流式处理视频失败: {e}")
            raise

    def resize_video(
        self,
        video_path: str,
        output_path: str,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        scale_factor: Optional[float] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ):
        """
        调整视频大小（流式处理）

        参数:
            video_path: 输入视频路径
            output_path: 输出视频路径
            target_width: 目标宽度
            target_height: 目标高度
            scale_factor: 缩放因子（优先级高于宽高）
            progress_callback: 进度回调函数
        """
        def resize_frame(frame: np.ndarray) -> np.ndarray:
            if scale_factor:
                new_width = int(frame.shape[1] * scale_factor)
                new_height = int(frame.shape[0] * scale_factor)
            else:
                new_width = target_width or frame.shape[1]
                new_height = target_height or frame.shape[0]

            return cv2.resize(frame, (new_width, new_height))

        self.process_video_stream(
            video_path,
            resize_frame,
            output_path,
            progress_callback
        )

    def get_video_info(self, video_path: str) -> dict:
        """
        获取视频信息（带缓存）

        参数:
            video_path: 视频文件路径

        返回:
            视频信息字典
        """
        cache_key = f"info:{video_path}"

        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        try:
            # 使用 PyAV 获取视频元数据
            container = av.open(video_path)
            stream = container.streams.video[0]

            fps = float(stream.average_rate) if stream.average_rate else 30.0
            frame_count = stream.frames if stream.frames else 0
            width = stream.width
            height = stream.height
            # 计算时长：若帧数已知则用帧数/fps，否则用 stream.duration
            if frame_count > 0 and fps > 0:
                duration = frame_count / fps
            elif stream.duration and stream.time_base:
                duration = float(stream.duration * stream.time_base)
            else:
                duration = 0.0

            info = {
                'fps': fps,
                'frame_count': frame_count,
                'width': width,
                'height': height,
                'duration': duration
            }

            container.close()

            # 缓存结果
            with self._lock:
                self._cache[cache_key] = info
                self._cache_order.append(cache_key)

                # 限制缓存大小
                if len(self._cache_order) > self.cache_size:
                    oldest_key = self._cache_order.pop(0)
                    del self._cache[oldest_key]

            return info

        except Exception as e:
            logger.error(f"获取视频信息失败: {e}")
            return {}

    def clear_cache(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._cache_order.clear()
            logger.info("视频处理器缓存已清空")

    def cleanup(self):
        """清理资源"""
        self.executor.shutdown(wait=True)
        self.clear_cache()
        logger.info("视频处理器已清理")


class LargeFileProcessor:
    """大文件处理器"""

    def __init__(self, chunk_size: int = 1024 * 1024):  # 默认1MB
        self.chunk_size = chunk_size

    def process_large_file(
        self,
        file_path: str,
        processor: Callable[[bytes], None],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ):
        """
        处理大文件（分块读取）

        参数:
            file_path: 文件路径
            processor: 数据块处理函数
            progress_callback: 进度回调函数 (current, total)
        """
        try:
            file_size = os.path.getsize(file_path)
            processed_size = 0

            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(self.chunk_size)
                    if not chunk:
                        break

                    processor(chunk)
                    processed_size += len(chunk)

                    # 进度回调
                    if progress_callback and processed_size % (10 * self.chunk_size) == 0:
                        progress_callback(processed_size, file_size)

            logger.info(f"大文件处理完成: {file_path}")

        except Exception as e:
            logger.error(f"处理大文件失败: {e}")
            raise

    def copy_large_file(
        self,
        src_path: str,
        dst_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ):
        """
        复制大文件（分块复制）

        参数:
            src_path: 源文件路径
            dst_path: 目标文件路径
            progress_callback: 进度回调函数
        """
        def write_chunk(chunk: bytes):
            with open(dst_path, 'ab') as f:
                f.write(chunk)

        # 确保目标文件不存在
        if os.path.exists(dst_path):
            os.remove(dst_path)

        self.process_large_file(src_path, write_chunk, progress_callback)

    def get_file_hash(
        self,
        file_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> str:
        """
        计算大文件的哈希值（分块计算）

        参数:
            file_path: 文件路径
            progress_callback: 进度回调函数

        返回:
            文件的MD5哈希值
        """
        import hashlib

        md5_hash = hashlib.md5()

        def update_hash(chunk: bytes):
            md5_hash.update(chunk)

        self.process_large_file(file_path, update_hash, progress_callback)

        return md5_hash.hexdigest()


# 全局处理器实例
_global_video_processor: Optional[OptimizedVideoProcessor] = None
_global_file_processor: Optional[LargeFileProcessor] = None


def get_video_processor(
    max_workers: int = 4,
    cache_size: int = 32
) -> OptimizedVideoProcessor:
    """获取全局视频处理器实例"""
    global _global_video_processor
    if _global_video_processor is None:
        _global_video_processor = OptimizedVideoProcessor(max_workers, cache_size)
    return _global_video_processor


def get_file_processor(
    chunk_size: int = 1024 * 1024
) -> LargeFileProcessor:
    """获取全局文件处理器实例"""
    global _global_file_processor
    if _global_file_processor is None:
        _global_file_processor = LargeFileProcessor(chunk_size)
    return _global_file_processor


def cleanup_processors():
    """清理所有处理器"""
    global _global_video_processor, _global_file_processor

    if _global_video_processor:
        _global_video_processor.cleanup()
        _global_video_processor = None

    if _global_file_processor:
        _global_file_processor = None

    logger.info("所有处理器已清理")