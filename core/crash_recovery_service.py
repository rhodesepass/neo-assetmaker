"""
崩溃恢复服务 - 检测未保存的临时文件
"""
import os
import json
import logging
import time
from typing import Optional, List, Dict
from dataclasses import dataclass
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


@dataclass
class RecoveryInfo:
    """恢复信息"""
    backup_path: str  # 备份文件路径
    timestamp: float  # 时间戳
    project_path: Optional[str] = None  # 原项目路径
    is_temp: bool = False  # 是否是临时项目


class CrashRecoveryService(QObject):
    """崩溃恢复服务"""

    recovery_found = pyqtSignal(list)  # 发现可恢复项目
    recovery_completed = pyqtSignal(str)  # 恢复完成
    error_occurred = pyqtSignal(str)  # 错误信号

    def __init__(self):
        super().__init__()
        self._recovery_dir: Optional[str] = None  # 恢复目录

    def initialize(self, base_dir: str):
        """初始化恢复服务"""
        self._recovery_dir = os.path.join(base_dir, ".recovery")
        os.makedirs(self._recovery_dir, exist_ok=True)
        logger.info(f"崩溃恢复服务已初始化: {self._recovery_dir}")

    def check_crash_recovery(self) -> List[RecoveryInfo]:
        """检查是否有可恢复的项目"""
        if not self._recovery_dir or not os.path.exists(self._recovery_dir):
            return []

        recovery_list = []

        try:
            # 扫描恢复目录
            for filename in os.listdir(self._recovery_dir):
                if not filename.endswith(".json"):
                    continue

                filepath = os.path.join(self._recovery_dir, filename)

                try:
                    # 读取恢复信息
                    with open(filepath, 'r', encoding='utf-8') as f:
                        recovery_data = json.load(f)

                    # 创建恢复信息
                    recovery_info = RecoveryInfo(
                        backup_path=recovery_data.get('backup_path', filepath),
                        timestamp=recovery_data.get('timestamp', time.time()),
                        project_path=recovery_data.get('project_path'),
                        is_temp=recovery_data.get('is_temp', False)
                    )

                    recovery_list.append(recovery_info)

                except Exception as e:
                    logger.warning(f"读取恢复文件失败 {filename}: {e}")

            # 按时间戳排序（最新的在前）
            recovery_list.sort(key=lambda x: x.timestamp, reverse=True)

            logger.info(f"发现 {len(recovery_list)} 个可恢复项目")
            return recovery_list

        except Exception as e:
            logger.error(f"检查崩溃恢复失败: {e}")
            return []

    def save_recovery_info(self, backup_path: str, project_path: Optional[str] = None, is_temp: bool = False):
        """保存恢复信息"""
        if not self._recovery_dir:
            return

        try:
            # 生成恢复文件名
            timestamp = int(time.time())
            recovery_filename = f"recovery_{timestamp}.json"
            recovery_path = os.path.join(self._recovery_dir, recovery_filename)

            # 创建恢复信息
            recovery_data = {
                'backup_path': backup_path,
                'timestamp': time.time(),
                'project_path': project_path,
                'is_temp': is_temp
            }

            # 保存恢复信息
            with open(recovery_path, 'w', encoding='utf-8') as f:
                json.dump(recovery_data, f, indent=2, ensure_ascii=False)

            logger.info(f"恢复信息已保存: {recovery_path}")

        except Exception as e:
            logger.error(f"保存恢复信息失败: {e}")

    def clear_recovery_info(self, recovery_path: str):
        """清除恢复信息"""
        try:
            if os.path.exists(recovery_path):
                os.remove(recovery_path)
                logger.info(f"恢复信息已清除: {recovery_path}")
        except Exception as e:
            logger.error(f"清除恢复信息失败: {e}")

    def clear_all_recovery(self):
        """清除所有恢复信息"""
        if not self._recovery_dir or not os.path.exists(self._recovery_dir):
            return

        try:
            for filename in os.listdir(self._recovery_dir):
                filepath = os.path.join(self._recovery_dir, filename)
                try:
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                    else:
                        import shutil
                        shutil.rmtree(filepath)
                    logger.debug(f"删除恢复文件: {filepath}")
                except Exception as e:
                    logger.warning(f"删除恢复文件失败: {e}")

            logger.info("已清除所有恢复信息")

        except Exception as e:
            logger.error(f"清除所有恢复信息失败: {e}")

    def recover_project(self, recovery_info: RecoveryInfo, target_path: str) -> bool:
        """恢复项目"""
        try:
            # 检查备份文件是否存在
            if not os.path.exists(recovery_info.backup_path):
                raise Exception(f"备份文件不存在: {recovery_info.backup_path}")

            # 读取备份内容
            with open(recovery_info.backup_path, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)

            # 保存到目标路径
            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)

            logger.info(f"项目已恢复: {target_path}")
            self.recovery_completed.emit(target_path)
            return True

        except Exception as e:
            logger.error(f"恢复项目失败: {e}")
            self.error_occurred.emit(str(e))
            return False

    def get_recovery_summary(self, recovery_info: RecoveryInfo) -> str:
        """获取恢复信息摘要"""
        timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(recovery_info.timestamp))
        
        summary = f"""
备份时间: {timestamp_str}
备份路径: {recovery_info.backup_path}
项目类型: {'临时项目' if recovery_info.is_temp else '永久项目'}
"""

        if recovery_info.project_path:
            summary += f"原项目路径: {recovery_info.project_path}\n"

        return summary

    def cleanup_old_recoveries(self, max_age_hours: int = 24):
        """清理旧的恢复信息"""
        if not self._recovery_dir or not os.path.exists(self._recovery_dir):
            return

        try:
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600
            cleaned_count = 0

            for filename in os.listdir(self._recovery_dir):
                if not filename.endswith(".json"):
                    continue

                filepath = os.path.join(self._recovery_dir, filename)

                try:
                    # 检查文件年龄
                    file_age = current_time - os.path.getmtime(filepath)

                    if file_age > max_age_seconds:
                        os.remove(filepath)
                        cleaned_count += 1
                        logger.debug(f"删除旧恢复文件: {filename}")

                except Exception as e:
                    logger.warning(f"删除恢复文件失败 {filename}: {e}")

            if cleaned_count > 0:
                logger.info(f"已清理 {cleaned_count} 个旧恢复文件")

        except Exception as e:
            logger.error(f"清理旧恢复信息失败: {e}")