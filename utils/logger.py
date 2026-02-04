"""
日志系统配置
"""
import os
import logging
import tempfile
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional


def setup_logger(log_dir: Optional[str] = None) -> logging.Logger:
    """
    配置应用日志系统

    Args:
        log_dir: 日志目录，默认为应用程序目录下的 logs 文件夹

    Returns:
        配置好的根日志记录器
    """
    if log_dir is None:
        # 使用应用程序目录（支持打包环境）
        from utils.file_utils import get_app_dir
        log_dir = os.path.join(get_app_dir(), 'logs')

    # 多级降级策略
    dirs_to_try = [
        log_dir,
    ]
    # 添加 AppData 目录作为备选
    appdata = os.getenv('LOCALAPPDATA')
    if appdata:
        dirs_to_try.append(os.path.join(appdata, 'ArknightsPassMaker', 'logs'))
    # 添加临时目录作为最后备选
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
        # 所有目录都不可用，只使用控制台输出
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

    # 日志格式
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter('[%(levelname)s] %(message)s')

    # 创建文件处理器，带异常处理
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

    # 控制台处理器 - 只记录 INFO 及以上
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()

    if file_handler:
        root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 记录启动信息
    if file_handler:
        root_logger.info(f"日志系统已初始化，日志文件: {log_file}")
    else:
        root_logger.warning("日志系统已初始化（仅控制台输出）")

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
        # 使用与 setup_logger 相同的目录逻辑
        from utils.file_utils import get_app_dir
        log_dir = os.path.join(get_app_dir(), 'logs')

    if not os.path.exists(log_dir):
        return

    cutoff_date = datetime.now() - timedelta(days=days)
    logger = logging.getLogger(__name__)

    for log_file in glob.glob(os.path.join(log_dir, 'app_*.log*')):
        try:
            # 从文件名提取日期
            filename = os.path.basename(log_file)
            if filename.startswith('app_') and len(filename) >= 12:
                date_str = filename[4:12]  # app_YYYYMMDD.log
                file_date = datetime.strptime(date_str, '%Y%m%d')

                if file_date < cutoff_date:
                    os.remove(log_file)
                    logger.info(f"已删除旧日志文件: {log_file}")
        except (ValueError, OSError) as e:
            logger.warning(f"清理日志文件时出错: {log_file}, {e}")
