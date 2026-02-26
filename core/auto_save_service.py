"""
自动保存服务 - 定期保存项目配置
"""
import os
import json
import logging
import time
from typing import Optional
from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

logger = logging.getLogger(__name__)


@dataclass
class AutoSaveConfig:
    """自动保存配置"""
    enabled: bool = True
    interval_seconds: int = 300  # 默认5分钟
    max_backups: int = 5  # 最多保留5个备份


class AutoSaveService(QObject):
    """自动保存服务"""

    saved = pyqtSignal(str)  # 保存成功信号，传递保存路径
    error_occurred = pyqtSignal(str)  # 错误信号

    def __init__(self, config: AutoSaveConfig = None):
        super().__init__()
        self.config = config or AutoSaveConfig()
        self._timer: Optional[QTimer] = None
        self._config_obj: Optional[object] = None  # 配置对象
        self._project_path: str = ""  # 项目路径
        self._base_dir: str = ""  # 基础目录
        self._last_save_time: float = 0  # 上次保存时间
        self._is_saving: bool = False  # 是否正在保存

    def start(self, config_obj: object, project_path: str, base_dir: str):
        """启动自动保存"""
        if not self.config.enabled:
            logger.info("自动保存已禁用")
            return

        self._config_obj = config_obj
        self._project_path = project_path
        self._base_dir = base_dir

        # 创建定时器
        if self._timer is None:
            self._timer = QTimer()
            self._timer.timeout.connect(self._on_timer)
        
        # 启动定时器
        interval_ms = self.config.interval_seconds * 1000
        self._timer.start(interval_ms)
        logger.info(f"自动保存已启动，间隔: {self.config.interval_seconds}秒")

    def stop(self):
        """停止自动保存"""
        if self._timer:
            self._timer.stop()
            logger.info("自动保存已停止")

    def save_now(self):
        """立即保存"""
        if not self._config_obj or not self._project_path:
            logger.warning("无法保存：配置对象或项目路径为空")
            return

        self._perform_save()

    def _on_timer(self):
        """定时器触发"""
        if self._is_saving:
            logger.debug("正在保存中，跳过本次自动保存")
            return

        self._perform_save()

    def _perform_save(self):
        """执行保存操作"""
        if not self._config_obj or not self._project_path:
            return

        try:
            self._is_saving = True

            # 检查是否有保存方法
            if not hasattr(self._config_obj, 'save_to_file'):
                logger.warning("配置对象没有 save_to_file 方法")
                return

            # 生成备份文件名
            backup_path = self._get_backup_path()

            # 保存到备份文件
            self._config_obj.save_to_file(backup_path)

            self._last_save_time = time.time()
            logger.info(f"自动保存成功: {backup_path}")
            self.saved.emit(backup_path)

        except Exception as e:
            logger.error(f"自动保存失败: {e}")
            self.error_occurred.emit(str(e))
        finally:
            self._is_saving = False

    def _get_backup_path(self) -> str:
        """获取备份文件路径"""
        if not self._project_path:
            # 如果没有项目路径，使用临时目录
            import tempfile
            temp_dir = tempfile.gettempdir()
            return os.path.join(temp_dir, f"autosave_{int(time.time())}.json")

        # 创建备份目录
        project_dir = os.path.dirname(self._project_path)
        backup_dir = os.path.join(project_dir, ".autosave")
        os.makedirs(backup_dir, exist_ok=True)

        # 生成备份文件名
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"autosave_{timestamp}.json"
        backup_path = os.path.join(backup_dir, backup_name)

        # 清理旧备份
        self._cleanup_old_backups(backup_dir)

        return backup_path

    def _cleanup_old_backups(self, backup_dir: str):
        """清理旧备份文件"""
        try:
            # 获取所有备份文件
            backup_files = []
            for filename in os.listdir(backup_dir):
                if filename.startswith("autosave_") and filename.endswith(".json"):
                    filepath = os.path.join(backup_dir, filename)
                    mtime = os.path.getmtime(filepath)
                    backup_files.append((filepath, mtime))

            # 按修改时间排序（最新的在前）
            backup_files.sort(key=lambda x: x[1], reverse=True)

            # 删除超过最大数量的备份
            if len(backup_files) > self.config.max_backups:
                for filepath, _ in backup_files[self.config.max_backups:]:
                    try:
                        os.remove(filepath)
                        logger.debug(f"删除旧备份: {filepath}")
                    except Exception as e:
                        logger.warning(f"删除备份失败: {e}")

        except Exception as e:
            logger.warning(f"清理旧备份失败: {e}")

    def get_latest_backup(self) -> Optional[str]:
        """获取最新的备份文件"""
        if not self._project_path:
            return None

        project_dir = os.path.dirname(self._project_path)
        backup_dir = os.path.join(project_dir, ".autosave")

        if not os.path.exists(backup_dir):
            return None

        try:
            # 获取所有备份文件
            backup_files = []
            for filename in os.listdir(backup_dir):
                if filename.startswith("autosave_") and filename.endswith(".json"):
                    filepath = os.path.join(backup_dir, filename)
                    mtime = os.path.getmtime(filepath)
                    backup_files.append((filepath, mtime))

            if not backup_files:
                return None

            # 返回最新的备份
            backup_files.sort(key=lambda x: x[1], reverse=True)
            return backup_files[0][0]

        except Exception as e:
            logger.error(f"获取最新备份失败: {e}")
            return None

    def clear_backups(self):
        """清理所有备份文件"""
        if not self._project_path:
            return

        project_dir = os.path.dirname(self._project_path)
        backup_dir = os.path.join(project_dir, ".autosave")

        if not os.path.exists(backup_dir):
            return

        try:
            for filename in os.listdir(backup_dir):
                filepath = os.path.join(backup_dir, filename)
                try:
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                    else:
                        import shutil
                        shutil.rmtree(filepath)
                    logger.debug(f"删除备份: {filepath}")
                except Exception as e:
                    logger.warning(f"删除备份失败: {e}")

            logger.info("已清理所有备份文件")

        except Exception as e:
            logger.error(f"清理备份失败: {e}")

    def update_config(self, config: AutoSaveConfig):
        """更新自动保存配置"""
        self.config = config
        logger.info(f"自动保存配置已更新: enabled={config.enabled}, interval={config.interval_seconds}s")