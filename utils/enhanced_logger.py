"""
增强的日志系统 - 支持日志轮转、过滤、搜索和导出
"""
import os
import logging
import re
from logging.handlers import RotatingFileHandler
from typing import List, Optional, Tuple
from datetime import datetime
from pathlib import Path


class EnhancedLogger:
    """增强的日志管理器"""

    def __init__(
        self,
        log_file: str,
        max_size: int = 10 * 1024 * 1024,  # 默认10MB
        backup_count: int = 5,
        log_level: str = "INFO"
    ):
        self.log_file = log_file
        self.max_size = max_size
        self.backup_count = backup_count
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        self._setup_handlers()

    def _setup_handlers(self):
        """设置日志处理器"""

        # 文件处理器（带轮转）
        file_handler = RotatingFileHandler(
            self.log_file,
            maxBytes=self.max_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.log_level)

        # 格式化
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def set_log_level(self, level: str):
        """设置日志级别"""
        log_level = getattr(logging, level.upper(), logging.INFO)
        self.log_level = log_level

        # 更新控制台处理器的日志级别
        for handler in self.logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
                handler.setLevel(log_level)

        self.logger.info(f"日志级别已设置为: {level}")

    def search_logs(
        self,
        keyword: str,
        level: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_results: int = 100
    ) -> List[Tuple[str, str, str, str]]:
        """
        搜索日志

        参数:
            keyword: 搜索关键词
            level: 日志级别过滤（DEBUG, INFO, WARNING, ERROR, CRITICAL）
            start_time: 开始时间（格式: YYYY-MM-DD HH:MM:SS）
            end_time: 结束时间（格式: YYYY-MM-DD HH:MM:SS）
            max_results: 最大结果数

        返回:
            List[Tuple[时间, 名称, 级别, 消息]]
        """
        results = []

        if not os.path.exists(self.log_file):
            return results

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    # 解析日志行
                    match = re.match(
                        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - (\S+) - (\w+) - (.+)',
                        line.strip()
                    )

                    if not match:
                        continue

                    timestamp, name, log_level, message = match.groups()

                    # 关键词过滤
                    if keyword and keyword.lower() not in message.lower():
                        continue

                    # 日志级别过滤
                    if level and level.upper() != log_level:
                        continue

                    # 时间范围过滤
                    if start_time or end_time:
                        log_time = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')

                        if start_time:
                            start_dt = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
                            if log_time < start_dt:
                                continue

                        if end_time:
                            end_dt = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S')
                            if log_time > end_dt:
                                continue

                    results.append((timestamp, name, log_level, message))

                    if len(results) >= max_results:
                        break

        except Exception as e:
            self.logger.error(f"搜索日志失败: {e}")

        return results

    def export_logs(
        self,
        output_file: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        level: Optional[str] = None
    ):
        """
        导出日志

        参数:
            output_file: 输出文件路径
            start_time: 开始时间（格式: YYYY-MM-DD HH:MM:SS）
            end_time: 结束时间（格式: YYYY-MM-DD HH:MM:SS）
            level: 日志级别过滤
        """
        try:
            # 搜索符合条件的日志
            logs = self.search_logs(
                keyword="",
                level=level,
                start_time=start_time,
                end_time=end_time,
                max_results=100000  # 导出时允许更多结果
            )

            # 写入文件
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"日志导出 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")

                for timestamp, name, log_level, message in logs:
                    f.write(f"[{timestamp}] [{log_level}] {name}: {message}\n")

            self.logger.info(f"日志已导出到: {output_file}")

        except Exception as e:
            self.logger.error(f"导出日志失败: {e}")
            raise

    def get_log_stats(self) -> dict:
        """获取日志统计信息"""
        stats = {
            'total_lines': 0,
            'by_level': {
                'DEBUG': 0,
                'INFO': 0,
                'WARNING': 0,
                'ERROR': 0,
                'CRITICAL': 0
            },
            'file_size': 0,
            'backup_files': []
        }

        try:
            # 统计主日志文件
            if os.path.exists(self.log_file):
                stats['file_size'] = os.path.getsize(self.log_file)

                with open(self.log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        stats['total_lines'] += 1

                        # 统计各级别数量
                        match = re.search(r' - (\w+) - ', line)
                        if match:
                            level = match.group(1)
                            if level in stats['by_level']:
                                stats['by_level'][level] += 1

            # 查找备份文件
            log_dir = os.path.dirname(self.log_file)
            log_name = os.path.basename(self.log_file)

            for file in os.listdir(log_dir):
                if file.startswith(log_name) and file != log_name:
                    backup_path = os.path.join(log_dir, file)
                    stats['backup_files'].append({
                        'name': file,
                        'path': backup_path,
                        'size': os.path.getsize(backup_path)
                    })

        except Exception as e:
            self.logger.error(f"获取日志统计失败: {e}")

        return stats

    def clear_logs(self):
        """清空日志文件"""
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    f.write("")
                self.logger.info("日志文件已清空")
        except Exception as e:
            self.logger.error(f"清空日志失败: {e}")
            raise

    def cleanup_old_backups(self, keep_count: int = None):
        """清理旧的备份文件"""
        if keep_count is None:
            keep_count = self.backup_count

        try:
            log_dir = os.path.dirname(self.log_file)
            log_name = os.path.basename(self.log_file)

            # 查找所有备份文件
            backup_files = []
            for file in os.listdir(log_dir):
                if file.startswith(log_name) and file != log_name:
                    backup_path = os.path.join(log_dir, file)
                    backup_files.append((backup_path, os.path.getmtime(backup_path)))

            # 按修改时间排序（从旧到新）
            backup_files.sort(key=lambda x: x[1])

            # 删除超过保留数量的旧备份
            if len(backup_files) > keep_count:
                for backup_path, _ in backup_files[:-keep_count]:
                    os.remove(backup_path)
                    self.logger.info(f"已删除旧备份: {backup_path}")

        except Exception as e:
            self.logger.error(f"清理旧备份失败: {e}")

    def get_logger(self) -> logging.Logger:
        """获取日志记录器"""
        return self.logger


# 全局日志管理器实例
_global_logger: Optional[EnhancedLogger] = None


def get_logger(
    log_file: str = None,
    max_size: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    log_level: str = "INFO"
) -> EnhancedLogger:
    """
    获取全局日志管理器实例

    参数:
        log_file: 日志文件路径（仅首次调用时使用）
        max_size: 最大日志文件大小（字节）
        backup_count: 备份文件数量
        log_level: 日志级别

    返回:
        EnhancedLogger 实例
    """
    global _global_logger

    if _global_logger is None:
        if log_file is None:
            raise ValueError("首次调用时必须提供 log_file 参数")

        _global_logger = EnhancedLogger(
            log_file=log_file,
            max_size=max_size,
            backup_count=backup_count,
            log_level=log_level
        )

    return _global_logger


def search_logs(
    keyword: str,
    level: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    max_results: int = 100
) -> List[Tuple[str, str, str, str]]:
    """搜索日志（便捷函数）"""
    logger = get_logger()
    return logger.search_logs(keyword, level, start_time, end_time, max_results)


def export_logs(
    output_file: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    level: Optional[str] = None
):
    """导出日志（便捷函数）"""
    logger = get_logger()
    logger.export_logs(output_file, start_time, end_time, level)


def get_log_stats() -> dict:
    """获取日志统计（便捷函数）"""
    logger = get_logger()
    return logger.get_log_stats()