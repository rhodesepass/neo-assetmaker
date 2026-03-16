"""
日志系统配置 - 支持日志轮转、搜索和导出
"""
import os
import logging
import re
import tempfile
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import List, Optional, Tuple


def setup_logger(log_dir: Optional[str] = None) -> logging.Logger:
    """
    配置应用日志系统

    Args:
        log_dir: 日志目录，默认为应用程序目录下的 logs 文件夹

    Returns:
        配置好的根日志记录器
    """
    if log_dir is None:
        from utils.file_utils import get_app_dir
        log_dir = os.path.join(get_app_dir(), 'logs')

    dirs_to_try = [
        log_dir,
    ]
    appdata = os.getenv('LOCALAPPDATA')
    if appdata:
        dirs_to_try.append(os.path.join(appdata, 'ArknightsPassMaker', 'logs'))
    dirs_to_try.append(os.path.join(tempfile.gettempdir(), 'ArknightsPassMaker_logs'))

    actual_log_dir = None
    for try_dir in dirs_to_try:
        try:
            os.makedirs(try_dir, exist_ok=True)
            actual_log_dir = try_dir
            break
        except (PermissionError, OSError):
            continue

    if actual_log_dir is None:
        print("[WARNING] 无法创建日志目录，仅使用控制台输出")
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.handlers.clear()
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        root_logger.addHandler(console_handler)
        return root_logger

    log_file = os.path.join(actual_log_dir, f'app_{datetime.now():%Y%m%d}.log')

    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter('[%(levelname)s] %(message)s')

    file_handler = None
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
    except (PermissionError, OSError) as e:
        print(f"[WARNING] 无法创建日志文件: {e}")

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()

    if file_handler:
        root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    if file_handler:
        root_logger.info(f"日志系统已初始化，日志文件: {log_file}")
    else:
        root_logger.warning("日志系统已初始化（仅控制台输出）")

    # 初始化日志管理器（仅用于搜索/导出/统计，不创建 handler）
    try:
        get_log_manager(log_file=log_file)
        root_logger.info("日志管理器已初始化")
    except Exception as e:
        root_logger.warning(f"日志管理器初始化失败: {e}")

    return root_logger


def cleanup_old_logs(log_dir: Optional[str] = None, days: int = 30):
    """
    清理超过指定天数的旧日志文件

    Args:
        log_dir: 日志目录
        days: 保留天数
    """
    import glob
    from datetime import timedelta

    if log_dir is None:
        from utils.file_utils import get_app_dir
        log_dir = os.path.join(get_app_dir(), 'logs')

    if not os.path.exists(log_dir):
        return

    cutoff_date = datetime.now() - timedelta(days=days)
    logger = logging.getLogger(__name__)

    for log_file in glob.glob(os.path.join(log_dir, 'app_*.log*')):
        try:
            filename = os.path.basename(log_file)
            if filename.startswith('app_') and len(filename) >= 12:
                date_str = filename[4:12]  # app_YYYYMMDD.log
                file_date = datetime.strptime(date_str, '%Y%m%d')

                if file_date < cutoff_date:
                    os.remove(log_file)
                    logger.info(f"已删除旧日志文件: {log_file}")
        except (ValueError, OSError) as e:
            logger.warning(f"清理日志文件时出错: {log_file}, {e}")


class LogManager:
    """日志文件管理工具 - 提供日志搜索、导出、统计功能

    不创建任何 handler，所有日志记录依赖 root logger 的 handler（通过 propagate=True）。
    """

    def __init__(self, log_file: str):
        self.log_file = log_file
        self.logger = logging.getLogger(__name__)

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
            List[Tuple[时间, 级别, 名称, 消息]]
        """
        results = []

        if not os.path.exists(self.log_file):
            return results

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    match = re.match(
                        r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(\w+)\] (\S+): (.+)',
                        line.strip()
                    )

                    if not match:
                        continue

                    timestamp, log_level, name, message = match.groups()

                    if keyword and keyword.lower() not in message.lower():
                        continue

                    if level and level.upper() != log_level:
                        continue

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

                    results.append((timestamp, log_level, name, message))

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
            logs = self.search_logs(
                keyword="",
                level=level,
                start_time=start_time,
                end_time=end_time,
                max_results=100000  # 导出时允许更多结果
            )

            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"日志导出 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")

                for timestamp, log_level, name, message in logs:
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
            if os.path.exists(self.log_file):
                stats['file_size'] = os.path.getsize(self.log_file)

                with open(self.log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        stats['total_lines'] += 1

                        match = re.search(r'\[(\w+)\]', line)
                        if match:
                            level = match.group(1)
                            if level in stats['by_level']:
                                stats['by_level'][level] += 1

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

    def cleanup_old_backups(self, keep_count: int = 5):
        """清理旧的备份文件"""
        try:
            log_dir = os.path.dirname(self.log_file)
            log_name = os.path.basename(self.log_file)

            backup_files = []
            for file in os.listdir(log_dir):
                if file.startswith(log_name) and file != log_name:
                    backup_path = os.path.join(log_dir, file)
                    backup_files.append((backup_path, os.path.getmtime(backup_path)))

            backup_files.sort(key=lambda x: x[1])

            if len(backup_files) > keep_count:
                for backup_path, _ in backup_files[:-keep_count]:
                    os.remove(backup_path)
                    self.logger.info(f"已删除旧备份: {backup_path}")

        except Exception as e:
            self.logger.error(f"清理旧备份失败: {e}")


# 全局日志管理器实例
_global_log_manager: Optional[LogManager] = None


def get_log_manager(log_file: str = None) -> LogManager:
    """
    获取全局日志管理器实例

    参数:
        log_file: 日志文件路径（仅首次调用时使用）

    返回:
        LogManager 实例
    """
    global _global_log_manager

    if _global_log_manager is None:
        if log_file is None:
            raise ValueError("首次调用时必须提供 log_file 参数")

        _global_log_manager = LogManager(log_file=log_file)

    return _global_log_manager


def search_logs(
    keyword: str,
    level: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    max_results: int = 100
) -> List[Tuple[str, str, str, str]]:
    """搜索日志（便捷函数）"""
    manager = get_log_manager()
    return manager.search_logs(keyword, level, start_time, end_time, max_results)


def export_logs(
    output_file: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    level: Optional[str] = None
):
    """导出日志（便捷函数）"""
    manager = get_log_manager()
    manager.export_logs(output_file, start_time, end_time, level)


def get_log_stats() -> dict:
    """获取日志统计（便捷函数）"""
    manager = get_log_manager()
    return manager.get_log_stats()
