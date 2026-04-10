# -*- coding: utf-8 -*-
"""
Doubao API Client
封装大模型调用，用于重要性评分和情景聚合
"""

import json
import logging
import re
from typing import Optional, Tuple, List
from dataclasses import dataclass

import config
from models import EBChunk

logger = logging.getLogger(__name__)


@dataclass
class ChunkAssignmentResult:
    """情景组块分配结果"""
    assigned_chunk_id: Optional[int]  # None表示新建
    is_new_chunk: bool
    updated_summary: str


class DoubaoClient:
    """
    Doubao API 客户端

    用于:
    1. 重要性评分 (Importance Scoring)
    2. 情景聚合 (Chunk Assignment)
    """

    def __init__(self):
        import os
        # 优先使用环境变量，其次使用config中的配置
        self.api_key = os.getenv('ARK_API_KEY') or config.DOUBAO_API_KEY
        self.endpoint = config.DOUBAO_ENDPOINT
        self.model = config.DOUBAO_MODEL
        self._client = None
        self._mock_mode = False

        # 检查是否需要使用Mock模式
        if self.api_key == "YOUR_API_KEY_HERE" or not self.api_key:
            logger.warning("Doubao API key not configured, using mock mode")
            self._mock_mode = True
            print("[DoubaoClient] Warning: API key not set, running in MOCK mode")
            print("[DoubaoClient] Set ARK_API_KEY environment variable or DOUBAO_API_KEY in config.py")
        else:
            self._init_client()

    def _init_client(self):
        """初始化真实的API客户端"""
        try:
            from volcenginesdkarkruntime import Ark
            # API key 通过环境变量 ARK_API_KEY 自动获取，或显式传入
            import os
            if os.getenv('ARK_API_KEY'):
                self._client = Ark(base_url=self.endpoint)
            else:
                self._client = Ark(api_key=self.api_key, base_url=self.endpoint)
            logger.info("Doubao client initialized successfully")
        except ImportError:
            logger.warning("volcenginesdkarkruntime not installed, falling back to mock mode")
            self._mock_mode = True
            print("[DoubaoClient] Warning: volcenginesdkarkruntime not installed, using MOCK mode")
        except Exception as e:
            logger.error(f"Failed to initialize Doubao client: {e}")
            self._mock_mode = True
            print(f"[DoubaoClient] Error: {e}, using MOCK mode")

    def score_importance(self, tier1_persona: str, opportunity_content: str) -> float:
        """
        评估干预事件的重要性

        Args:
            tier1_persona: Tier 1 用户画像文本
            opportunity_content: 干预事件内容

        Returns:
            重要性得分 (0-1)
        """
        prompt = config.PROMPT_IMPORTANCE_SCORING.format(
            tier1_persona=tier1_persona,
            opportunity_content=opportunity_content
        )

        # 记录API请求
        logger.info(f"[API Request] Importance Scoring")
        logger.info(f"[API Request] Prompt:\n{prompt[:500]}...")

        if self._mock_mode:
            logger.info("[API Response] Using MOCK mode")
            return self._mock_score_importance(opportunity_content)

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )

            result_text = response.choices[0].message.content

            # 记录API响应
            logger.info(f"[API Response] Result: {result_text}")

            # 提取数字
            score = self._extract_score(result_text)
            logger.info(f"[API Result] Importance Score: {score}")
            return score

        except Exception as e:
            logger.error(f"Error calling Doubao API for importance scoring: {e}")
            return self._mock_score_importance(opportunity_content)

    def _mock_score_importance(self, opportunity_content: str) -> float:
        """
        Mock模式下的重要性评分
        基于关键词进行简单判断
        """
        content_lower = opportunity_content.lower()

        # 高重要性关键词
        high_keywords = ["导师", "论文", "毕设", "答辩", "血糖", "健康", "紧急", "截止"]
        # 中等重要性关键词
        medium_keywords = ["提醒", "通知", "消息", "任务", "作业", "会议"]
        # 低重要性关键词
        low_keywords = ["广告", "推荐", "游戏", "视频", "外卖", "淘宝"]

        # 计算得分
        score = 0.3  # 基础分

        for kw in high_keywords:
            if kw in content_lower:
                score += 0.2

        for kw in medium_keywords:
            if kw in content_lower:
                score += 0.1

        for kw in low_keywords:
            if kw in content_lower:
                score -= 0.2

        # 限制在0-1范围
        return max(0.0, min(1.0, score))

    def _extract_score(self, text: str) -> float:
        """从响应文本中提取分数"""
        # 尝试直接解析浮点数
        try:
            return float(text)
        except ValueError:
            pass

        # 使用正则表达式提取数字
        match = re.search(r"(\d+\.?\d*)", text)
        if match:
            return float(match.group(1))

        # 默认返回中等分数
        return 0.5

    def assign_chunk(
        self,
        new_pm_content: str,
        existing_chunks: List[EBChunk]
    ) -> ChunkAssignmentResult:
        """
        将新的PM项分配到情景组块

        Args:
            new_pm_content: 新PM项的内容
            existing_chunks: 现有的EB组块列表

        Returns:
            ChunkAssignmentResult: 分配结果
        """
        # 构建现有组块的描述
        if existing_chunks:
            chunks_desc = "\n".join([
                f"组块 {chunk.chunk_id}: {chunk.summary}"
                for chunk in existing_chunks
            ])
        else:
            chunks_desc = "(暂无现有组块)"

        user_prompt = config.PROMPT_CHUNK_ASSIGNMENT.format(
            existing_chunks=chunks_desc,
            new_pm_item=new_pm_content
        )
        system_prompt = config.PROMPT_CHUNK_ASSIGNMENT_SYSTEM

        # 记录API请求
        logger.info(f"[API Request] Chunk Assignment")
        logger.info(f"[API Request] New PM: {new_pm_content}")
        logger.info(f"[API Request] Existing chunks:\n{chunks_desc}")
        logger.info(f"[API Request] System prompt:\n{system_prompt}")
        logger.info(f"[API Request] User prompt:\n{user_prompt}")

        if self._mock_mode:
            logger.info("[API Response] Using MOCK mode")
            return self._mock_assign_chunk(new_pm_content, existing_chunks)

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
            )

            result_text = response.choices[0].message.content

            # 记录API响应
            logger.info(f"[API Response] Raw response: {result_text}")

            result = self._parse_chunk_result(result_text, existing_chunks)

            # 记录解析结果
            logger.info(f"[API Result] Chunk Assignment: is_new={result.is_new_chunk}, "
                       f"chunk_id={result.assigned_chunk_id}, summary={result.updated_summary}")

            return result

        except Exception as e:
            logger.error(f"Error calling Doubao API for chunk assignment: {e}")
            return self._mock_assign_chunk(new_pm_content, existing_chunks)

    def _mock_assign_chunk(
        self,
        new_pm_content: str,
        existing_chunks: List[EBChunk]
    ) -> ChunkAssignmentResult:
        """
        Mock模式下的组块分配
        基于关键词进行简单分类
        """
        content_lower = new_pm_content.lower()

        # 定义类别关键词
        categories = {
            "学业": ["论文", "导师", "毕设", "答辩", "作业", "课程", "实验"],
            "健康": ["血糖", "喝水", "休息", "运动", "吃药", "饮食"],
            "社交": ["消息", "微信", "室友", "朋友", "同学"],
            "娱乐": ["游戏", "视频", "B站", "抖音", "音乐"]
        }

        # 确定新内容属于哪个类别
        new_category = None
        for cat, keywords in categories.items():
            for kw in keywords:
                if kw in content_lower:
                    new_category = cat
                    break
            if new_category:
                break

        if not new_category:
            new_category = "其他"

        # 检查现有组块中是否有匹配的
        for chunk in existing_chunks:
            for cat, keywords in categories.items():
                for kw in keywords:
                    if kw in chunk.summary and cat == new_category:
                        return ChunkAssignmentResult(
                            assigned_chunk_id=chunk.chunk_id,
                            is_new_chunk=False,
                            updated_summary=f"{cat}相关事项"
                        )

        # 需要新建组块
        return ChunkAssignmentResult(
            assigned_chunk_id=None,
            is_new_chunk=True,
            updated_summary=f"{new_category}相关事项"
        )

    def _parse_chunk_result(
        self,
        result_text: str,
        existing_chunks: List[EBChunk]
    ) -> ChunkAssignmentResult:
        """解析组块分配结果"""
        try:
            # 去除可能的markdown代码块标记
            result_text = re.sub(r"```json\s*", "", result_text)
            result_text = re.sub(r"```\s*", "", result_text)
            result_text = result_text.strip()

            # 模型可能输出多行JSON，只取第一行
            first_line = result_text.split("\n")[0].strip()

            # 尝试用json.loads解析（能处理单行完整JSON）
            try:
                result = json.loads(first_line)
            except json.JSONDecodeError:
                # 如果单行解析失败，尝试从完整文本中提取第一个JSON对象
                match = re.search(r'\{[^{}]*\}', result_text)
                if match:
                    result = json.loads(match.group(0))
                else:
                    raise

            # 兼容新旧两种字段名
            assigned_id = result.get("id") or result.get("assigned_chunk_id")
            summary = result.get("summary") or result.get("updated_summary", "新组块")

            if assigned_id == "new" or assigned_id is None:
                return ChunkAssignmentResult(
                    assigned_chunk_id=None,
                    is_new_chunk=True,
                    updated_summary=summary
                )
            else:
                chunk_id = int(assigned_id)
                # 验证ID是否有效
                valid_ids = [c.chunk_id for c in existing_chunks]
                if chunk_id in valid_ids:
                    return ChunkAssignmentResult(
                        assigned_chunk_id=chunk_id,
                        is_new_chunk=False,
                        updated_summary=summary
                    )
                else:
                    # ID无效，新建组块
                    return ChunkAssignmentResult(
                        assigned_chunk_id=None,
                        is_new_chunk=True,
                        updated_summary=summary
                    )

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse chunk result: {e}, using fallback")
            # 回退到新建组块
            return ChunkAssignmentResult(
                assigned_chunk_id=None,
                is_new_chunk=True,
                updated_summary="新组块"
            )


# 全局单例
_client = None


def get_doubao_client() -> DoubaoClient:
    """获取全局 Doubao 客户端单例"""
    global _client
    if _client is None:
        _client = DoubaoClient()
    return _client
