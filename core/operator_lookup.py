"""
干员信息查询模块

功能：
- 加载 character_table.json 和 handbookpos_table.json
- 精确匹配干员名称
- 模糊匹配（使用 thefuzz）
- 返回干员完整信息（名称、代号、职业、势力、颜色）
"""
import os
import json
import logging
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OperatorInfo:
    """干员信息数据类"""
    char_id: str           # 角色ID，如 "char_002_amiya"
    name: str              # 英文名，如 "Amiya"
    name_zh: str           # 中文名，如 "阿米娅"
    code: str              # 代号，如 "UNK0"
    nation: Optional[str]  # 势力，如 "rhodes"
    op_class: str          # 职业，如 "CASTER"
    color: str             # 颜色，如 "#0098dc"


# 职业ID映射表
CLASSID_DICT: Dict[int, str] = {
    512: "VANGUARD",
    1: "GUARD",
    4: "DEFENDER",
    32: "CASTER",
    2: "SNIPER",
    8: "MEDIC",
    16: "SUPPORTER",
    64: "SPECIALIST",
    128: "UNKNOWN",
    256: "UNKNOWN",
}


class OperatorLookup:
    """干员查询类"""

    def __init__(self, data_dir: Optional[str] = None):
        """
        初始化干员查询

        Args:
            data_dir: 数据目录路径，默认使用 resources/data
        """
        self._data_dir = data_dir or self._get_default_data_dir()
        self._operators: Dict[str, OperatorInfo] = {}  # char_id -> OperatorInfo
        self._name_index: Dict[str, str] = {}  # lowercase_name -> char_id
        self._name_list: List[str] = []  # 所有英文名列表（用于模糊匹配）
        self._loaded = False

    @staticmethod
    def _get_default_data_dir() -> str:
        """获取默认数据目录"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, "resources", "data")

    def load(self) -> bool:
        """
        加载干员数据

        Returns:
            是否加载成功
        """
        if self._loaded:
            return True

        char_table_path = os.path.join(self._data_dir, "character_table.json")
        handbook_path = os.path.join(self._data_dir, "handbookpos_table.json")

        if not os.path.exists(char_table_path):
            logger.error(f"角色表文件不存在: {char_table_path}")
            return False

        try:
            # 第一阶段：加载颜色信息
            char_color_dict: Dict[str, str] = {}
            if os.path.exists(handbook_path):
                with open(handbook_path, "r", encoding="utf-8") as f:
                    handbookpos_data = json.load(f)

                for _, group_data in handbookpos_data.get("groupList", {}).items():
                    for force in group_data.get("forceDataList", []):
                        color = "#" + force.get("color", "ff0000")
                        for char_id in force.get("charList", []):
                            if char_id.startswith("char_"):
                                char_color_dict[char_id] = color

                logger.info(f"已加载 {len(char_color_dict)} 个干员颜色信息")
            else:
                logger.warning(f"干员颜色表文件不存在: {handbook_path}")

            # 第二阶段：加载干员数据
            with open(char_table_path, "r", encoding="utf-8") as f:
                char_data = json.load(f)

            characters = char_data.get("Characters", {})
            for char_id, char_info in characters.items():
                if not char_id.startswith("char_"):
                    continue

                name = char_info.get("Appellation", "")
                name_zh = char_info.get("Name", "")
                code = char_info.get("DisplayNumber", "")
                nation = char_info.get("NationId")
                profession_id = char_info.get("Profession", 0)
                op_class = CLASSID_DICT.get(profession_id, "UNKNOWN")
                color = char_color_dict.get(char_id, "#ff0000")

                operator_info = OperatorInfo(
                    char_id=char_id,
                    name=name,
                    name_zh=name_zh,
                    code=code,
                    nation=nation,
                    op_class=op_class,
                    color=color
                )

                self._operators[char_id] = operator_info

                # 建立索引
                name_lower = name.lower()
                if name_lower in self._name_index:
                    logger.debug(f"干员名称重复: {name} ({char_id} vs {self._name_index[name_lower]})")
                self._name_index[name_lower] = char_id
                self._name_list.append(name)

            logger.info(f"已加载 {len(self._operators)} 个干员信息")
            self._loaded = True
            return True

        except Exception as e:
            logger.error(f"加载干员数据失败: {e}")
            return False

    def lookup_exact(self, name: str) -> Optional[OperatorInfo]:
        """
        精确匹配干员名称

        Args:
            name: 干员英文名（不区分大小写）

        Returns:
            干员信息，未找到返回 None
        """
        if not self._loaded:
            self.load()

        name_lower = name.lower().strip()
        char_id = self._name_index.get(name_lower)
        if char_id:
            return self._operators.get(char_id)
        return None

    def lookup_fuzzy(self, name: str, threshold: int = 80, limit: int = 5) -> List[Tuple[OperatorInfo, int]]:
        """
        模糊匹配干员名称

        Args:
            name: 干员名称
            threshold: 相似度阈值（0-100）
            limit: 返回结果数量限制

        Returns:
            匹配结果列表，按相似度降序排列 [(OperatorInfo, score), ...]
        """
        if not self._loaded:
            self.load()

        if not self._name_list:
            return []

        try:
            from thefuzz import process

            results = process.extract(name.lower(), self._name_list, limit=limit)
            matched = []

            for result in results:
                # thefuzz返回格式可能是 (name, score) 或 (name, score, index)
                matched_name = result[0]
                score = result[1]

                if score >= threshold:
                    char_id = self._name_index.get(matched_name.lower())
                    if char_id:
                        operator_info = self._operators.get(char_id)
                        if operator_info:
                            matched.append((operator_info, score))

            return matched

        except ImportError:
            logger.error("thefuzz 未安装，无法使用模糊匹配")
            return []

    def lookup(self, name: str, threshold: int = 80) -> Tuple[Optional[OperatorInfo], bool, List[Tuple[OperatorInfo, int]]]:
        """
        查询干员（先精确后模糊）

        Args:
            name: 干员名称
            threshold: 模糊匹配阈值

        Returns:
            (匹配结果, 是否精确匹配, 候选列表)
            - 精确匹配时: (info, True, [])
            - 模糊匹配时: (best_match, False, candidates)
            - 无匹配时: (None, False, [])
        """
        # 精确匹配
        exact_match = self.lookup_exact(name)
        if exact_match:
            return exact_match, True, []

        # 模糊匹配
        fuzzy_matches = self.lookup_fuzzy(name, threshold)
        if fuzzy_matches:
            best_match = fuzzy_matches[0][0]
            return best_match, False, fuzzy_matches

        return None, False, []

    def get_all_operators(self) -> List[OperatorInfo]:
        """获取所有干员列表"""
        if not self._loaded:
            self.load()
        return list(self._operators.values())

    def get_class_icon_filename(self, op_class: str) -> str:
        """
        获取职业图标文件名

        Args:
            op_class: 职业名称，如 "CASTER"

        Returns:
            图标文件名，如 "caster.png"
        """
        return f"{op_class.lower()}.png"

    def search(self, keyword: str, limit: int = 10) -> List[OperatorInfo]:
        """
        搜索干员（支持英文名和中文名）

        Args:
            keyword: 搜索关键词
            limit: 结果数量限制

        Returns:
            匹配的干员列表
        """
        if not self._loaded:
            self.load()

        keyword_lower = keyword.lower().strip()
        results = []

        for operator_info in self._operators.values():
            # 匹配英文名
            if keyword_lower in operator_info.name.lower():
                results.append(operator_info)
                continue

            # 匹配中文名
            if keyword in operator_info.name_zh:
                results.append(operator_info)
                continue

            # 匹配代号
            if keyword_lower in operator_info.code.lower():
                results.append(operator_info)
                continue

            if len(results) >= limit:
                break

        return results[:limit]


# 模块级单例
_default_lookup: Optional[OperatorLookup] = None


def get_operator_lookup() -> OperatorLookup:
    """获取默认的干员查询实例（单例）"""
    global _default_lookup
    if _default_lookup is None:
        _default_lookup = OperatorLookup()
        _default_lookup.load()
    return _default_lookup
