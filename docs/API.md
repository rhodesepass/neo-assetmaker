# API 文档

## 自动保存服务

### AutoSaveConfig

自动保存配置类。

#### 属性

- `enabled: bool` - 是否启用自动保存（默认：True）
- `interval_seconds: int` - 保存间隔，单位秒（默认：300）
- `max_backups: int` - 最大备份数量（默认：5）

#### 示例

```python
from core.auto_save_service import AutoSaveConfig

config = AutoSaveConfig(
    enabled=True,
    interval_seconds=300,  # 5分钟
    max_backups=5
)
```

---

### AutoSaveService

自动保存服务类。

#### 方法

##### `__init__(config: AutoSaveConfig = None)`

初始化自动保存服务。

**参数**:
- `config`: 自动保存配置对象

**示例**:
```python
from core.auto_save_service import AutoSaveService, AutoSaveConfig

config = AutoSaveConfig()
service = AutoSaveService(config)
```

##### `start(config_obj: object, project_path: str, base_dir: str)`

启动自动保存服务。

**参数**:
- `config_obj`: 配置对象（需要有to_dict()方法）
- `project_path`: 项目文件路径
- `base_dir`: 基础目录

**示例**:
```python
service.start(config_obj, "project.json", "/path/to/project")
```

##### `stop()`

停止自动保存服务。

**示例**:
```python
service.stop()
```

##### `save_now() -> str`

立即保存项目。

**返回**: 保存的文件路径

**示例**:
```python
saved_path = service.save_now()
print(f"已保存到: {saved_path}")
```

##### `get_latest_backup() -> Optional[str]`

获取最新的备份文件路径。

**返回**: 最新备份文件路径，如果没有备份则返回None

**示例**:
```python
backup_path = service.get_latest_backup()
if backup_path:
    print(f"最新备份: {backup_path}")
```

##### `clear_backups(base_dir: str)`

清理所有备份文件。

**参数**:
- `base_dir`: 基础目录

**示例**:
```python
service.clear_backups("/path/to/project")
```

##### `update_config(config: AutoSaveConfig)`

更新自动保存配置。

**参数**:
- `config`: 新的配置对象

**示例**:
```python
new_config = AutoSaveConfig(interval_seconds=600)
service.update_config(new_config)
```

#### 信号

##### `saved(str)`

保存成功信号，传递保存路径。

**示例**:
```python
service.saved.connect(lambda path: print(f"已保存: {path}"))
```

##### `error_occurred(str)`

错误信号，传递错误消息。

**示例**:
```python
service.error_occurred.connect(lambda msg: print(f"错误: {msg}"))
```

---

## 崩溃恢复服务

### RecoveryInfo

恢复信息数据类。

#### 属性

- `backup_path: str` - 备份文件路径
- `timestamp: float` - 时间戳
- `project_path: Optional[str]` - 原项目路径
- `is_temp: bool` - 是否是临时项目

#### 示例

```python
from core.crash_recovery_service import RecoveryInfo
import time

info = RecoveryInfo(
    backup_path="/path/to/backup.json",
    timestamp=time.time(),
    project_path="/path/to/project.json",
    is_temp=False
)
```

---

### CrashRecoveryService

崩溃恢复服务类。

#### 方法

##### `__init__()`

初始化崩溃恢复服务。

**示例**:
```python
from core.crash_recovery_service import CrashRecoveryService

service = CrashRecoveryService()
```

##### `initialize(base_dir: str)`

初始化恢复服务。

**参数**:
- `base_dir`: 基础目录

**示例**:
```python
service.initialize("/path/to/project")
```

##### `check_crash_recovery() -> List[RecoveryInfo]`

检查是否有可恢复的项目。

**返回**: 可恢复项目列表

**示例**:
```python
recovery_list = service.check_crash_recovery()
for info in recovery_list:
    print(f"发现可恢复项目: {info.backup_path}")
```

##### `save_recovery_info(recovery_info: RecoveryInfo)`

保存恢复信息。

**参数**:
- `recovery_info`: 恢复信息对象

**示例**:
```python
service.save_recovery_info(recovery_info)
```

##### `clear_recovery_info(recovery_info: RecoveryInfo)`

清除指定的恢复信息。

**参数**:
- `recovery_info`: 恢复信息对象

**示例**:
```python
service.clear_recovery_info(recovery_info)
```

##### `clear_all_recovery()`

清除所有恢复信息。

**示例**:
```python
service.clear_all_recovery()
```

##### `recover_project(recovery_info: RecoveryInfo, target_path: str) -> bool`

恢复项目到指定位置。

**参数**:
- `recovery_info`: 恢复信息对象
- `target_path`: 目标路径

**返回**: 是否恢复成功

**示例**:
```python
success = service.recover_project(recovery_info, "/path/to/restore")
if success:
    print("项目恢复成功")
```

##### `get_recovery_summary() -> dict`

获取恢复摘要。

**返回**: 恢复摘要字典

**示例**:
```python
summary = service.get_recovery_summary()
print(f"可恢复项目数: {summary['total_count']}")
print(f"临时项目数: {summary['temp_count']}")
print(f"永久项目数: {summary['permanent_count']}")
```

##### `cleanup_old_recoveries(max_age_hours: int = 24)`

清理旧的恢复信息。

**参数**:
- `max_age_hours`: 最大保留小时数（默认：24）

**示例**:
```python
service.cleanup_old_recoveries(max_age_hours=24)
```

#### 信号

##### `recovery_found(List[RecoveryInfo])`

发现可恢复项目信号。

**示例**:
```python
service.recovery_found.connect(lambda list: print(f"发现 {len(list)} 个可恢复项目"))
```

##### `recovery_completed(str)`

恢复完成信号，传递恢复的路径。

**示例**:
```python
service.recovery_completed.connect(lambda path: print(f"已恢复到: {path}"))
```

##### `error_occurred(str)`

错误信号，传递错误消息。

**示例**:
```python
service.error_occurred.connect(lambda msg: print(f"错误: {msg}"))
```

---

## 错误处理服务

### ErrorInfo

错误信息数据类。

#### 属性

- `original_error: Exception` - 原始错误对象
- `user_message: str` - 用户友好的错误消息
- `error_type: str` - 错误类型
- `severity: str` - 严重程度（info, warning, error, critical）
- `suggestions: List[str]` - 解决建议列表
- `technical_details: str` - 技术详情

#### 示例

```python
from core.error_handler import ErrorInfo

error_info = ErrorInfo(
    original_error=Exception("Test error"),
    user_message="用户友好的错误消息",
    error_type="Exception",
    severity="error",
    suggestions=["建议1", "建议2"],
    technical_details="技术详情"
)
```

---

### ErrorHandler

错误处理器类。

#### 方法

##### `__init__()`

初始化错误处理器。

**示例**:
```python
from core.error_handler import ErrorHandler

handler = ErrorHandler()
```

##### `handle_error(error: Exception, context: str = "") -> ErrorInfo`

处理错误，返回用户友好的错误信息。

**参数**:
- `error`: 异常对象
- `context`: 错误上下文

**返回**: 错误信息对象

**示例**:
```python
try:
    # 你的代码
    pass
except Exception as e:
    error_info = handler.handle_error(e, "操作上下文")
    print(f"错误: {error_info.user_message}")
```

##### `show_error_dialog(error_info: ErrorInfo, parent=None)`

显示错误对话框。

**参数**:
- `error_info`: 错误信息对象
- `parent`: 父窗口

**示例**:
```python
try:
    # 你的代码
    pass
except Exception as e:
    error_info = handler.handle_error(e, "操作上下文")
    handler.show_error_dialog(error_info, parent=self)
```

##### `translate_exception(exception: Exception, context: str = "") -> str`

将异常转换为用户友好的消息。

**参数**:
- `exception`: 异常对象
- `context`: 错误上下文

**返回**: 用户友好的错误消息

**示例**:
```python
try:
    # 你的代码
    pass
except Exception as e:
    user_message = handler.translate_exception(e, "操作上下文")
    print(f"错误: {user_message}")
```

#### 信号

##### `error_occurred(ErrorInfo)`

错误发生信号。

**示例**:
```python
handler.error_occurred.connect(lambda info: print(f"错误: {info.user_message}"))
```

---

## 便捷函数

### 自动保存

```python
from core.auto_save_service import AutoSaveService, AutoSaveConfig

# 创建服务
config = AutoSaveConfig()
service = AutoSaveService(config)

# 启动自动保存
service.start(config_obj, "project.json", "/path/to/project")

# 立即保存
saved_path = service.save_now()

# 停止自动保存
service.stop()
```

### 崩溃恢复

```python
from core.crash_recovery_service import CrashRecoveryService

# 创建服务
service = CrashRecoveryService()
service.initialize("/path/to/project")

# 检查可恢复项目
recovery_list = service.check_crash_recovery()

# 恢复项目
if recovery_list:
    service.recover_project(recovery_list[0], "/path/to/restore")
```

### 错误处理

```python
from core.error_handler import show_error, handle_error

# 显示错误对话框
try:
    # 你的代码
    pass
except Exception as e:
    show_error(e, "操作上下文", parent=self)

# 处理错误
try:
    # 你的代码
    pass
except Exception as e:
    error_info = handle_error(e, "操作上下文")
    print(f"错误: {error_info.user_message}")
```