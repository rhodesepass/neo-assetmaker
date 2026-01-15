"""
配置管理器 - 管理固件配置的加载和访问

提供单例模式的配置管理，支持：
1. 加载默认内置配置
2. 从 JSON 文件加载自定义配置
3. 按名称获取配置
"""

import logging
import os
from typing import Dict, Optional

from config.firmware_config import FirmwareConfig

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    配置管理器 - 单例模式

    用法:
        # 初始化（应用启动时调用一次）
        ConfigManager.initialize()

        # 获取配置
        config = ConfigManager.get_firmware()
        fps = config.fps
        name_start_frame = config.name_start_frame
    """

    _instance: Optional["ConfigManager"] = None
    _firmware_configs: Dict[str, FirmwareConfig] = {}
    _default_config: Optional[FirmwareConfig] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def initialize(cls, config_dir: str = None):
        """
        初始化配置管理器

        Args:
            config_dir: 配置文件目录，默认为 config/firmware/
        """
        if cls._initialized:
            return

        instance = cls()

        # 加载默认配置
        cls._default_config = FirmwareConfig.get_default()
        logger.info("已加载默认固件配置")

        # 扫描配置目录
        if config_dir is None:
            # 获取相对于当前模块的路径
            module_dir = os.path.dirname(os.path.abspath(__file__))
            config_dir = os.path.join(module_dir, 'firmware')

        if os.path.exists(config_dir):
            instance._load_configs_from_dir(config_dir)
        else:
            logger.warning(f"配置目录不存在: {config_dir}")

        cls._initialized = True
        logger.info(f"配置管理器初始化完成，已加载 {len(cls._firmware_configs)} 个配置")

    def _load_configs_from_dir(self, config_dir: str):
        """从目录加载所有配置文件"""
        for filename in os.listdir(config_dir):
            if filename.endswith('.firmware.json'):
                filepath = os.path.join(config_dir, filename)
                try:
                    config = FirmwareConfig.load_from_file(filepath)
                    name = config.name or os.path.splitext(filename)[0]
                    self._firmware_configs[name] = config
                    logger.info(f"已加载固件配置: {name} ({filepath})")
                except Exception as e:
                    logger.error(f"加载配置失败 {filepath}: {e}")

    @classmethod
    def get_firmware(cls, name: str = None) -> FirmwareConfig:
        """
        获取固件配置

        Args:
            name: 配置名称，None 表示使用默认配置

        Returns:
            FirmwareConfig 实例
        """
        # 自动初始化
        if not cls._initialized:
            cls.initialize()

        if name and name in cls._firmware_configs:
            return cls._firmware_configs[name]

        # 如果请求的名称不存在但有已加载的配置，使用第一个
        if name is None and cls._firmware_configs:
            # 优先使用名为 "default" 的配置
            if "default" in cls._firmware_configs:
                return cls._firmware_configs["default"]
            # 否则使用 extracted 的配置
            for config_name, config in cls._firmware_configs.items():
                if "extracted" in config_name:
                    return config
            # 使用第一个加载的配置
            return next(iter(cls._firmware_configs.values()))

        # 返回默认配置
        if cls._default_config is None:
            cls._default_config = FirmwareConfig.get_default()
        return cls._default_config

    @classmethod
    def register_firmware(cls, name: str, config: FirmwareConfig):
        """
        注册固件配置

        Args:
            name: 配置名称
            config: FirmwareConfig 实例
        """
        cls._firmware_configs[name] = config
        logger.info(f"已注册固件配置: {name}")

    @classmethod
    def list_configs(cls) -> list:
        """列出所有已加载的配置名称"""
        return list(cls._firmware_configs.keys())

    @classmethod
    def reset(cls):
        """重置配置管理器（主要用于测试）"""
        cls._firmware_configs.clear()
        cls._default_config = None
        cls._initialized = False
