"""
干员数据库管理器
从character_table.json加载干员信息，提供搜索和职业查询功能
"""
import json
import os
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher
from config.constants import PROFESSION_CODE_MAP, PROFESSION_NAME_MAP


class OperatorDatabase:
    """干员数据库"""
    
    def __init__(self):
        self._operators: Dict[str, dict] = {}
        self._name_to_code: Dict[str, str] = {}
        self._loaded = False
    
    def load(self, data_path: Optional[str] = None) -> bool:
        """
        加载干员数据库
        
        Args:
            data_path: character_table.json文件路径，如果为None则使用默认路径
        
        Returns:
            是否加载成功
        """
        if self._loaded:
            return True
        
        try:
            if data_path is None:
                # 默认路径：resources/data/character_table.json
                current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                data_path = os.path.join(current_dir, "resources", "data", "character_table.json")
            
            if not os.path.exists(data_path):
                print(f"干员数据库文件不存在: {data_path}")
                return False
            
            with open(data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            characters = data.get("Characters", {})
            
            for char_id, char_data in characters.items():
                name = char_data.get("Name", "")
                if not name:
                    continue
                
                profession_code = char_data.get("Profession", 0)
                profession = PROFESSION_CODE_MAP.get(profession_code, "")
                
                operator_info = {
                    "id": char_id,
                    "name": name,
                    "profession_code": profession_code,
                    "profession": profession,
                    "profession_name": PROFESSION_NAME_MAP.get(profession, ""),
                    "appellation": char_data.get("Appellation", ""),
                    "rarity": char_data.get("Rarity", 0),
                    "description": char_data.get("Description", "")
                }
                
                self._operators[name] = operator_info
                self._name_to_code[name.lower()] = name
            
            self._loaded = True
            print(f"成功加载干员数据库，共 {len(self._operators)} 个干员")
            return True
            
        except Exception as e:
            print(f"加载干员数据库失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def search(self, query: str, limit: int = 10) -> List[Tuple[str, float]]:
        """
        模糊搜索干员
        
        Args:
            query: 搜索关键词
            limit: 返回结果数量限制
        
        Returns:
            匹配结果列表，每个元素为(干员名称, 相似度)的元组
        """
        if not self._loaded:
            self.load()
        
        if not query:
            return []
        
        query_lower = query.lower()
        results = []
        
        for name in self._operators:
            name_lower = name.lower()
            
            # 完全匹配
            if query_lower == name_lower:
                results.append((name, 1.0))
                continue
            
            # 包含匹配
            if query_lower in name_lower:
                similarity = len(query) / len(name)
                results.append((name, similarity))
                continue
            
            # 模糊匹配
            similarity = SequenceMatcher(None, query_lower, name_lower).ratio()
            if similarity > 0.3:  # 相似度阈值
                results.append((name, similarity))
        
        # 按相似度排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:limit]
    
    def get_operator_info(self, name: str) -> Optional[dict]:
        """
        获取干员信息
        
        Args:
            name: 干员名称
        
        Returns:
            干员信息字典，如果不存在则返回None
        """
        if not self._loaded:
            self.load()
        
        return self._operators.get(name)
    
    def get_operator_profession(self, name: str) -> Optional[str]:
        """
        获取干员职业
        
        Args:
            name: 干员名称
        
        Returns:
            职业代码（如"vanguard"），如果不存在则返回None
        """
        info = self.get_operator_info(name)
        if info:
            return info.get("profession")
        return None
    
    def get_operator_profession_name(self, name: str) -> Optional[str]:
        """
        获取干员职业名称
        
        Args:
            name: 干员名称
        
        Returns:
            职业中文名称（如"先锋"），如果不存在则返回None
        """
        info = self.get_operator_info(name)
        if info:
            return info.get("profession_name")
        return None
    
    def get_all_operators(self) -> List[str]:
        """
        获取所有干员名称
        
        Returns:
            干员名称列表
        """
        if not self._loaded:
            self.load()
        
        return sorted(self._operators.keys())
    
    def get_operators_by_profession(self, profession: str) -> List[str]:
        """
        根据职业获取干员列表
        
        Args:
            profession: 职业代码（如"vanguard"）
        
        Returns:
            干员名称列表
        """
        if not self._loaded:
            self.load()
        
        results = []
        for name, info in self._operators.items():
            if info.get("profession") == profession:
                results.append(name)
        
        return sorted(results)


# 全局单例
_operator_db = OperatorDatabase()


def get_operator_db() -> OperatorDatabase:
    """获取干员数据库单例"""
    return _operator_db
