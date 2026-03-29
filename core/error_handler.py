"""
错误处理服务 - 增强错误提示的用户友好性
"""
import os
import logging
import traceback
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


@dataclass
class ErrorInfo:
    """错误信息"""
    original_error: Exception  # 原始错误
    user_message: str  # 用户友好的错误消息
    error_type: str  # 错误类型
    severity: str  # 严重程度：info, warning, error, critical
    suggestions: List[str]  # 解决建议
    technical_details: str  # 技术细节


class ErrorHandler(QObject):
    """错误处理器"""

    error_occurred = pyqtSignal(ErrorInfo)  # 错误发生信号

    def __init__(self):
        super().__init__()
        self._error_patterns: Dict[str, Tuple[str, List[str]]] = {}
        self._init_error_patterns()

    def _init_error_patterns(self):
        """初始化错误模式"""
        self._error_patterns = {
            # 文件相关错误
            'FileNotFoundError': (
                '文件未找到',
                [
                    '请检查文件路径是否正确',
                    '确认文件是否存在',
                    '检查文件权限'
                ]
            ),
            'PermissionError': (
                '权限不足',
                [
                    '请以管理员身份运行程序',
                    '检查文件权限设置',
                    '关闭正在使用该文件的其他程序'
                ]
            ),
            'OSError': (
                '系统错误',
                [
                    '检查磁盘空间是否充足',
                    '确认文件路径格式正确',
                    '尝试重启程序'
                ]
            ),

            # 视频相关错误
            'cv2.error': (
                '视频处理错误',
                [
                    '确认视频文件格式正确（支持MP4, AVI, MOV等）',
                    '检查视频文件是否损坏',
                    '尝试使用其他视频编码器'
                ]
            ),
            'VideoLoadError': (
                '视频加载失败',
                [
                    '确认视频文件格式正确',
                    '检查视频文件是否损坏',
                    '尝试使用其他视频文件'
                ]
            ),

            # 网络相关错误
            'ConnectionError': (
                '网络连接失败',
                [
                    '检查网络连接是否正常',
                    '确认防火墙设置',
                    '尝试使用代理或VPN'
                ]
            ),
            'TimeoutError': (
                '连接超时',
                [
                    '检查网络连接速度',
                    '稍后重试',
                    '尝试使用其他网络'
                ]
            ),
            'requests.exceptions.RequestException': (
                '网络请求失败',
                [
                    '检查网络连接',
                    '确认目标服务器是否正常运行',
                    '稍后重试'
                ]
            ),

            # JSON相关错误
            'json.JSONDecodeError': (
                'JSON解析错误',
                [
                    '确认JSON文件格式正确',
                    '检查文件编码是否为UTF-8',
                    '使用JSON验证工具检查文件'
                ]
            ),
            'ValidationError': (
                '配置验证失败',
                [
                    '检查配置项是否符合要求',
                    '参考配置文件示例',
                    '查看错误详情了解具体问题'
                ]
            ),

            # 内存相关错误
            'MemoryError': (
                '内存不足',
                [
                    '关闭其他占用内存的程序',
                    '尝试处理较小的文件',
                    '增加系统虚拟内存'
                ]
            ),

            # 固件烧录相关错误
            'FlasherError': (
                '固件烧录失败',
                [
                    '确认设备连接正常',
                    '检查驱动是否正确安装',
                    '确认固件文件完整',
                    '尝试重新连接设备'
                ]
            ),
            'DeviceNotFoundError': (
                '设备未找到',
                [
                    '确认设备已连接到电脑',
                    '检查USB线是否正常',
                    '尝试更换USB接口',
                    '确认驱动已正确安装'
                ]
            ),

            # 通用错误
            'RuntimeError': (
                '运行时错误',
                [
                    '查看错误详情了解具体问题',
                    '尝试重启程序',
                    '检查程序配置是否正确'
                ]
            ),
            'ValueError': (
                '数值错误',
                [
                    '检查输入的数值是否在有效范围内',
                    '确认数据格式正确',
                    '参考配置说明'
                ]
            ),
            'KeyError': (
                '键值错误',
                [
                    '检查配置文件是否完整',
                    '确认配置项名称正确',
                    '参考配置文件示例'
                ]
            ),
            'AttributeError': (
                '属性错误',
                [
                    '检查程序版本是否最新',
                    '尝试重启程序',
                    '联系开发者获取帮助'
                ]
            ),
        }

    def handle_error(self, error: Exception, context: str = "") -> ErrorInfo:
        """处理错误，返回用户友好的错误信息"""
        error_type = type(error).__name__
        error_message = str(error)

        # 查找匹配的错误模式
        user_message, suggestions = self._find_error_pattern(error_type, error_message)

        # 如果没有找到匹配的模式，使用通用处理
        if not user_message:
            user_message = f"发生未知错误: {error_type}"
            suggestions = [
                '查看错误详情了解具体问题',
                '尝试重启程序',
                '联系开发者获取帮助'
            ]

        # 确定严重程度
        severity = self._determine_severity(error_type)

        # 生成技术细节
        technical_details = self._generate_technical_details(error, context)

        # 创建错误信息
        error_info = ErrorInfo(
            original_error=error,
            user_message=user_message,
            error_type=error_type,
            severity=severity,
            suggestions=suggestions,
            technical_details=technical_details
        )

        # 记录错误
        self._log_error(error_info)

        # 发出错误信号
        self.error_occurred.emit(error_info)

        return error_info

    def _find_error_pattern(self, error_type: str, error_message: str) -> Tuple[Optional[str], List[str]]:
        """查找匹配的错误模式"""
        # 精确匹配
        if error_type in self._error_patterns:
            return self._error_patterns[error_type]

        # 模糊匹配
        for pattern_type, (message, suggestions) in self._error_patterns.items():
            if pattern_type.lower() in error_type.lower() or pattern_type.lower() in error_message.lower():
                return message, suggestions

        return None, []

    def _determine_severity(self, error_type: str) -> str:
        """确定错误严重程度"""
        critical_errors = [
            'MemoryError',
            'SystemError',
            'FlasherError'
        ]

        error_errors = [
            'FileNotFoundError',
            'PermissionError',
            'OSError',
            'ConnectionError',
            'TimeoutError',
            'RuntimeError'
        ]

        warning_errors = [
            'ValueError',
            'KeyError',
            'AttributeError',
            'ValidationError'
        ]

        if error_type in critical_errors:
            return 'critical'
        elif error_type in error_errors:
            return 'error'
        elif error_type in warning_errors:
            return 'warning'
        else:
            return 'info'

    def _generate_technical_details(self, error: Exception, context: str) -> str:
        """生成技术细节"""
        details = f"错误类型: {type(error).__name__}\n"
        details += f"错误消息: {str(error)}\n"

        if context:
            details += f"上下文: {context}\n"

        # 添加堆栈跟踪
        details += "\n堆栈跟踪:\n"
        details += traceback.format_exc()

        return details

    def _log_error(self, error_info: ErrorInfo):
        """记录错误"""
        log_message = f"用户错误: {error_info.user_message} ({error_info.error_type})"

        if error_info.severity == 'critical':
            logger.critical(log_message)
        elif error_info.severity == 'error':
            logger.error(log_message)
        elif error_info.severity == 'warning':
            logger.warning(log_message)
        else:
            logger.info(log_message)

    def show_error_dialog(self, error_info: ErrorInfo, parent=None):
        """显示错误对话框"""
        from PyQt6.QtWidgets import QMessageBox

        # 构建错误消息
        message = f"{error_info.user_message}\n\n"

        if error_info.suggestions:
            message += "建议解决方案:\n"
            for i, suggestion in enumerate(error_info.suggestions, 1):
                message += f"{i}. {suggestion}\n"

        # 根据严重程度选择图标
        if error_info.severity == 'critical':
            icon = QMessageBox.Icon.Critical
            title = "严重错误"
        elif error_info.severity == 'error':
            icon = QMessageBox.Icon.Warning
            title = "错误"
        elif error_info.severity == 'warning':
            icon = QMessageBox.Icon.Warning
            title = "警告"
        else:
            icon = QMessageBox.Icon.Information
            title = "提示"

        # 显示错误对话框
        msg_box = QMessageBox(icon, title, message, QMessageBox.StandardButton.Ok, parent)
        msg_box.setDetailedText(error_info.technical_details)
        msg_box.exec()

    def translate_exception(self, exception: Exception, context: str = "") -> str:
        """将异常转换为用户友好的消息"""
        error_info = self.handle_error(exception, context)
        return error_info.user_message


# 全局错误处理器实例
_global_error_handler = None


def get_error_handler() -> ErrorHandler:
    """获取全局错误处理器实例"""
    global _global_error_handler
    if _global_error_handler is None:
        _global_error_handler = ErrorHandler()
    return _global_error_handler


def handle_error(error: Exception, context: str = "") -> ErrorInfo:
    """处理错误（便捷函数）"""
    handler = get_error_handler()
    return handler.handle_error(error, context)


def show_error(error: Exception, context: str = "", parent=None):
    """显示错误对话框（便捷函数）"""
    handler = get_error_handler()
    error_info = handler.handle_error(error, context)
    handler.show_error_dialog(error_info, parent)


def translate_error(error: Exception) -> str:
    """翻译错误消息（便捷函数）"""
    handler = get_error_handler()
    return handler.translate_exception(error)