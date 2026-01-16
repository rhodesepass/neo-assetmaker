"""
日志系统配置
"""
import os
import logging
import tempfile
from datetime import datetime
from logging.handlers import RotatingFileHandler


def setup_logger(log_dir: str = None) -> logging.Logger:
    """
    配置应用日志系统

    Args:
        log_dir: 日志目录，默认为 AppData 目录，降级到临时目录

    Returns:
        配置好的根日志记录器
    """
    # 确定日志目录
    if log_dir is None:
        # 优先使用 AppData 目录
        appdata = os.getenv('LOCALAPPDATA')
        if appdata:
            log_dir = os.path.join(appdata, 'ArknightsPassMaker', 'logs')
        else:
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 'logs'
            )

    # 创建日志目录，带权限降级
    try:
        os.makedirs(log_dir, exist_ok=True)
    except PermissionError:
        # 降级到临时目录
        log_dir = os.path.join(tempfile.gettempdir(), 'ArknightsPassMaker_logs')
        os.makedirs(log_dir, exist_ok=True)

    # 日志文件名（按日期）
    log_file = os.path.join(
        log_dir, f'app_{datetime.now():%Y%m%d}.log'
    )

    # 日志格式
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter(
        '[%(levelname)s] %(message)s'
    )

    # 文件处理器 - 记录所有级别
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    # 控制台处理器 - 只记录 INFO 及以上
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 清除现有处理器（避免重复）
    root_logger.handlers.clear()

    # 添加处理器
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 记录启动信息
    root_logger.info(f"日志系统已初始化，日志文件: {log_file}")

    return root_logger


def cleanup_old_logs(log_dir: str = None, days: int = 30):
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
        appdata = os.getenv('LOCALAPPDATA')
        if appdata:
            log_dir = os.path.join(appdata, 'ArknightsPassMaker', 'logs')
        else:
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 'logs'
            )

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
