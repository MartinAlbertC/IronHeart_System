# -*- coding: utf-8 -*-
"""
C 层 LLM 客户端

封装与大模型的交互，用于夜间反思：
1. Tier2 长期记忆特征提取（行为习惯总结）
2. Identity 身份推断（过滤情绪化表达）
3. Tier1 用户画像更新
4. 事件冲突检测（识别气话、情绪化表达）

API 配置:
- 默认使用 DeepSeek API，可通过环境变量覆盖
"""

import json
import logging
import os
import urllib.request
from typing import Dict, List, Any, Optional

logger = logging.getLogger("c_layer.llm_client")


class CLayerLLMClient:
    """C 层 LLM 客户端"""

    def __init__(self, model_name: str = None):
        """
        初始化 LLM 客户端

        Args:
            model_name: 模型名称，默认使用 DeepSeek
        """
        # 默认使用 DeepSeek API，可通过环境变量覆盖
        self.api_key = os.getenv("DECALLM_API_KEY", "sk-51da30b4ce9c4712a3a9035f4c405441")
        self.base_url = os.getenv("RECALLM_BASE_URL", "https://api.deepseek.com")
        self.model = model_name or os.getenv("RECALLM_MODEL", "deepseek-chat")

        # 检查 API Key 是否配置
        self._mock_mode = False
        if not self.api_key:
            logger.warning("LLM API key 未配置，将使用 mock 模式")
            self._mock_mode = True

    def _call_llm(self, system_prompt: str, user_content: Any, temperature: float = 0.3) -> Optional[Dict[str, Any]]:
        """
        通用 LLM 调用方法

        Args:
            system_prompt: System prompt
            user_content: User prompt 内容（可以是字符串或字典）
            temperature: 温度参数

        Returns:
            LLM 返回的 JSON 对象，或 None（失败时）
        """
        if self._mock_mode:
            return None

        try:
            # 构建请求
            if isinstance(user_content, dict):
                user_text = json.dumps(user_content, ensure_ascii=False)
            else:
                user_text = str(user_content)

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_text,
                    },
                ],
                "temperature": temperature,
                "stream": False,
            }

            req = urllib.request.Request(
                url=f"{self.base_url}/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")

            body = json.loads(raw)
            text = (
                body.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

            # 提取 JSON
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1:
                logger.warning(f"LLM 未返回 JSON，原始内容：{text[:300]}")
                return None

            data = json.loads(text[start : end + 1])
            return data

        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
            logger.error(f"LLM HTTP 错误：{e.code} {detail[:200]}")
            return None
        except Exception as e:
            logger.error(f"LLM 调用失败：{e}")
            return None

    # ============================================================
    # Tier2 长期记忆特征提取（行为习惯总结）
    # ============================================================

    def extract_tier2_memories(
        self,
        entity_id: str,
        events: List[Dict[str, Any]],
        existing_tier2_memories: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        从 Tier3 事件列表中提取 Tier2 长期记忆

        夜间反思核心功能:
        1. 记录流水账 - 客观记录当天发生的事件
        2. 总结行为习惯 - 从重复事件中提取稳定的行为模式
        3. 过滤情绪化表达 - 不提取孤立的、情绪化的言论

        数据流:
        - Tier3 事件（当天）+ 现有 Tier2 记忆 → 合并/更新 Tier2

        Args:
            entity_id: 实体 ID
            events: Tier3 事件列表（通常是当天的事件）
            existing_tier2_memories: 现有的 Tier2 记忆列表（用于合并和避免重复）

        Returns:
            {
                "memories": [
                    {
                        "memory_text": "用户喜欢夜跑，有规律的夜间跑步习惯",
                        "base_importance": 0.8,
                        "category": "preference|habit|behavior|fact"
                    }
                ],
                "updated_memories": [  // 需要更新的现有记忆
                    {
                        "memory_id": "nm_xxx",
                        "memory_text": "更新后的文本",
                        "base_importance": 0.9  // 提高重要性
                    }
                ],
                "reason": "检测到 5 次重复的夜跑行为"
            }
        """
        system_prompt = (
            "你是长期记忆提取器，负责夜间反思。你的任务是从当天的短期事件中提取长期记忆。\n\n"
            "【数据输入】\n"
            "- today_events: 当天的 Tier3 事件列表（包含 summary 和 speaker 信息）\n"
            "- existing_memories: 现有的 Tier2 长期记忆（可能包含该实体往期的记忆）\n\n"
            "【核心原则】\n"
            "1. 记录流水账：客观记录当天发生的重要事件，格式为 `[YYYY-MM-DD] 人名 + 活动`\n"
            "2. 总结行为习惯：从重复事件中提取稳定的行为模式\n"
            "3. 过滤情绪化表达：气话、情绪化言论不提取为事实\n"
            "4. 合并同类项：如果现有记忆中已有类似内容，更新它而不是新增\n\n"
            "【人名提取】\n"
            "从事件 summary 中提取真实人名（如'李四'、'王老师'），不要用 entity_id 或 alias\n"
            "示例:\n"
            "- '李四说：我最近经常去踢足球' → 人名='李四'，特征='喜欢足球'\n"
            "- '张三对李四说：有空啊' → 涉及人名='张三'，'李四'\n"
            "- '检测到李四的人脸' → 人名='李四'\n\n"
            "【重要：说话人 vs 被描述人】\n"
            "- 只提取属于当前 entity_id 的记忆，不要把别人说的内容误归给说话人\n"
            "- '张三对李四说：我也喜欢足球' → 这是张三在说关于足球，但足球爱好属于张三本人，不属于李四\n"
            "- '张三说：原来是老师啊' → 张三在评价王老师，'老师'身份属于王老师，不属于张三\n"
            "- speaker 字段标明说话人，记忆应归属于说话人自身的行为/偏好，不是说话人提到的其他人\n\n"
            "【语义化映射】\n"
            "技术字段必须转换为人话:\n"
            "- 'face_detection' → '出现' 或 '露面'\n"
            "- 'conversation_act' → '交流' 或 '对话'\n"
            "- 'exercise' → '运动'\n"
            "记忆文本示例：`[2026-04-21] 李四 出现` 而不是 `[2026-04-21] 李四 face_detection`\n\n"
            "【提取规则】\n"
            "1. 同一行为重复出现 ≥3 次 → 提取为习惯/偏好\n"
            "2. 重复 2 次 → 记录为'近期频繁...'\n"
            "3. 仅 1 次且带有强烈情绪色彩 → 不提取，或标记为'一时气话'\n"
            "4. 如果现有记忆中已有类似内容 → 更新重要性，合并描述\n"
            "5. 记忆文本应该是抽象的特征描述，不是具体事件的流水账\n\n"
            "【情绪过滤示例】\n"
            "- '我不想再认你这个姐姐了' → 这是气话，不提取'不是姐姐'\n"
            "- '我讨厌你' → 这是情绪发泄，不提取为关系事实\n"
            "- '再也不来了' → 结合上下文判断，如果是争吵中说的，不提取\n\n"
            "【输出说明】\n"
            "- memories: 新增的记忆列表\n"
            "- updated_memories: 需要更新的现有记忆（附带 memory_id）\n\n"
            "只输出一个 JSON 对象，格式为：\n"
            "{\n"
            '  "memories": [\n'
            "    {\n"
            '      "memory_text": "记忆文本（包含人名和语义化的活动）",\n'
            '      "base_importance": 0.5,\n'
            '      "category": "preference|habit|behavior|fact"\n'
            "    }\n"
            "  ],\n"
            '  "updated_memories": [\n'
            "    {\n"
            '      "memory_id": "nm_xxx",\n'
            '      "memory_text": "更新后的文本",\n'
            '      "base_importance": 0.8\n'
            "    }\n"
            "  ],\n"
            '  "reason": "提取理由说明"\n'
            "}\n\n"
            "category 说明:\n"
            "- preference: 偏好（如'喜欢足球'）\n"
            "- habit: 习惯（如'每天夜跑'）\n"
            "- behavior: 行为模式（如'说话语速快'）\n"
            "- fact: 客观事实（如'住在北京市朝阳区'）"
        )

        # 构建当天事件摘要（直接丢给 LLM，让它提取人名和特征）
        today_event_summaries = []
        for e in events[:30]:
            summary = {
                "time": e.get("start_ts", "")[:16],
                "summary": e.get("summary", ""),  # LLM 从 summary 中提取人名
                "semantic_type": e.get("semantic_type", "unknown"),
            }
            # 添加 extra_slots 中的关键信息
            extra = e.get("extra_slots", {})
            if extra:
                if extra.get("speaker"):
                    summary["speaker"] = extra["speaker"]  # LLM 从说话人提取人名
                if extra.get("topic"):
                    summary["topic"] = extra["topic"]
                if extra.get("activity_type"):
                    summary["activity_type"] = extra["activity_type"]
            today_event_summaries.append(summary)

        # 构建现有 Tier2 记忆摘要
        existing_memories_summary = []
        if existing_tier2_memories:
            for m in existing_tier2_memories[:20]:
                existing_memories_summary.append({
                    "memory_id": m.get("memory_id", ""),
                    "memory_text": m.get("memory_text", ""),
                    "base_importance": m.get("base_importance", 0.5),
                })

        user_content = {
            "entity_id": entity_id,
            "today_event_count": len(today_event_summaries),
            "today_events": today_event_summaries,
            "existing_memories": existing_memories_summary,
        }

        result = self._call_llm(system_prompt, user_content, temperature=0.3)

        if result:
            result.setdefault("memories", [])
            result.setdefault("updated_memories", [])
            result.setdefault("reason", "")
            result["fallback"] = False
        else:
            result = {
                "memories": [],
                "updated_memories": [],
                "reason": "LLM 调用失败，降级为规则合并",
                "fallback": True,
            }

        return result

    # ============================================================
    # Identity 身份推断（过滤情绪化表达）
    # ============================================================

    def infer_identity(self, entity_id: str, current_labels: str, evidence: List[str]) -> Dict[str, Any]:
        """
        从对话证据中推断身份 labels 和名称

        核心原则：
        1. 区分事实陈述和情绪化表达
        2. 气话、争吵中的话不作为身份依据
        3. 需要多次、多场景的确认才能更新身份

        Args:
            entity_id: 当前实体 ID（可能是临时代号如 alias_C）
            current_labels: 当前 labels
            evidence: 证据列表（对话摘要）

        Returns:
            {
                "entity_id": "alias_C",
                "proposed_name": "王老师",
                "proposed_labels": "老师，大学教师",
                "confidence": 0.95,
                "reason": "从对话中明确提到...",
                "is_emotional": false  // 是否包含情绪化表达
            }
        """
        system_prompt = (
            "你是 identity 更新建议器，负责从对话中推断身份。\n\n"
            "【核心原则】\n"
            "1. 区分事实陈述和情绪化表达\n"
            "2. 气话、争吵中的话不作为身份依据\n"
            "3. 需要多次、多场景的确认才能更新身份\n\n"
            "【重要：说话人 vs 被描述人】\n"
            "- identity 的 labels 应描述该 entity 本人，不是该 entity 在对话中提到的其他人\n"
            "- '张三说：原来是老师啊' → '老师'身份属于被描述者（王老师），不属于张三\n"
            "- '张三对李四说：我也喜欢足球' → '喜欢足球'属于张三自己，不属于李四\n"
            "- 不要把别人谈论的特征误归给当前 entity\n\n"
            "【情绪化表达识别】\n"
            "以下情况标记为情绪化表达，不作为身份依据:\n"
            "- '我不想再认你这个姐姐了' → 这是气话，不改变'是姐姐'的事实\n"
            "- '我讨厌你' → 情绪发泄，不改变关系\n"
            "- '你根本不是我朋友' → 争吵中的话，不提取\n"
            "- '我再也不来了' → 如果是争吵后说的，不提取为'不再来'\n\n"
            "【confidence 评分标准】\n"
            "- 0.9-1.0: 本人亲口确认 + 多场景验证\n"
            "- 0.7-0.9: 多次对话中提及，一致性强\n"
            "- 0.5-0.7: 单次提及，但语气肯定\n"
            "- <0.5: 不确定，或仅在情绪化场景提及\n\n"
            "只输出一个 JSON 对象，格式为：\n"
            "{\n"
            '  "entity_id": "...",\n'
            '  "proposed_name": "..." 或 null,\n'
            '  "proposed_labels": "标签 1，标签 2",\n'
            '  "confidence": 0.95,\n'
            '  "reason": "推断理由",\n'
            '  "is_emotional": false  // 证据中是否包含情绪化表达\n'
            "}\n"
            "confidence 取 0 到 1 之间的小数。不要输出 JSON 以外内容。"
        )

        user_content = {
            "entity_id": entity_id,
            "current_labels": current_labels or "",
            "evidence": evidence[:20],
            "task": "基于证据返回 JSON 建议，注意过滤情绪化表达",
        }

        result = self._call_llm(system_prompt, user_content, temperature=0.0)

        if result:
            result.setdefault("entity_id", entity_id)
            result.setdefault("proposed_name", None)
            result.setdefault("proposed_labels", current_labels or "")
            result.setdefault("confidence", 0.0)
            result.setdefault("reason", "")
            result.setdefault("is_emotional", False)
        else:
            result = {
                "entity_id": entity_id,
                "proposed_name": None,
                "proposed_labels": current_labels or "",
                "confidence": 0.0,
                "reason": "LLM 调用失败",
            }

        return result

    # ============================================================
    # Tier1 用户画像更新
    # ============================================================

    def update_tier1_persona(
        self,
        tier2_memories: List[Dict[str, Any]],
        current_facts: Dict[str, Any],
        user_events: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        从 Tier2 长期记忆中提取 Tier1 核心画像

        数据流：Tier2（稳定记忆）→ Tier1（核心画像）

        核心原则：
        1. 只提取稳定的、重复的特征
        2. 过滤一时的冲动、气话
        3. 健康状况需要谨慎对待
        4. Tier2 已经过筛选和合并，是更稳定的数据源

        Args:
            tier2_memories: Tier2 长期记忆列表（主要数据源）
            current_facts: 当前的 critical_facts
            user_events: 用户相关的 Tier3 事件列表（辅助数据源，可选）

        Returns:
            {
                "critical_facts": {
                    "preferences": ["喜欢夜跑"],
                    "habits": ["每天 20:00 跑步"],
                    "health_constraints": [],
                    "core_goals": [],
                    "relationships": []
                },
                "reason": "从 Tier2 中提取出以上特征"
            }
        """
        system_prompt = (
            "你是 Tier1 用户画像提取器，负责从 Tier2 长期记忆中提取核心画像。\n\n"
            "【数据流】\n"
            "- 输入：Tier2 长期记忆（已经过筛选、合并、去重）\n"
            "- 输出：Tier1 核心画像（最稳定、最重要的用户特征）\n\n"
            "【核心原则】\n"
            "1. 只提取稳定的、重复出现的特征\n"
            "2. 过滤一时的冲动、气话（Tier2 可能仍有遗漏）\n"
            "3. 健康状况需要谨慎对待（不要从单次记忆提取健康约束）\n"
            "4. 关系类事实需要多方确认\n"
            "5. 优先从 Tier2 中提取，而不是 Tier3 原始事件\n\n"
            "【Tier2 vs Tier3】\n"
            "- Tier2: 已经合并了多天的重复事件，更稳定\n"
            "- Tier3: 当天的原始事件，可能有噪音\n"
            "- 本方法主要从 Tier2 提取，Tier3 仅作上下文参考\n\n"
            "【不提取的情况】\n"
            "- 孤立的记忆：仅 1 次提及且无后续验证\n"
            "- 情绪化表达：'我讨厌运动'（单次，无其他佐证）\n"
            "- 冲动言论：'明天开始减肥'（无后续行动）\n"
            "- 单次健康提及：'有点感冒'（非长期症状）\n\n"
            "【提取标准】\n"
            "- 习惯：Tier2 中有 ≥2 条相关记忆\n"
            "- 偏好：Tier2 中明确提及且语气稳定\n"
            "- 健康：医生诊断或长期症状（Tier2 中多次提及）\n"
            "- 关系：多方确认或长期稳定\n\n"
            "只输出一个 JSON 对象，格式为：\n"
            "{\n"
            '  "critical_facts": {\n'
            '    "preferences": [],     // 用户偏好（如"喜欢足球"）\n'
            '    "habits": [],          // 用户习惯（如"每天夜跑"）\n'
            '    "health_constraints": [],  // 健康禁忌\n'
            '    "core_goals": [],      // 核心目标\n'
            '    "relationships": []    // 重要关系\n'
            "  },\n"
            '  "reason": "提取理由说明"\n'
            "}\n"
            "如果没有发现值得提取的特征，返回空的 critical_facts。"
        )

        # 构建 Tier2 记忆摘要（主要数据源）
        tier2_summaries = []
        for m in tier2_memories[:30]:
            summary = {
                "memory_id": m.get("memory_id", ""),
                "memory_text": m.get("memory_text", ""),
                "base_importance": m.get("base_importance", 0.5),
                "category": m.get("category", "unknown"),  # 如果有分类
            }
            tier2_summaries.append(summary)

        # 构建 Tier3 事件摘要（辅助数据源，可选）
        event_summaries = []
        if user_events:
            for e in user_events[:20]:
                summary = {
                    "time": e.get("start_ts", "")[:16],
                    "type": e.get("semantic_type", "unknown"),
                    "summary": e.get("summary", ""),
                    "dialogue_act": e.get("dialogue_act", "unknown"),
                }
                extra = e.get("extra_slots", {})
                if extra:
                    if extra.get("topic"):
                        summary["topic"] = extra["topic"]
                    if extra.get("emotion"):
                        summary["emotion"] = extra["emotion"]
                event_summaries.append(summary)

        user_content = {
            "current_facts": current_facts,
            "tier2_memory_count": len(tier2_summaries),
            "tier2_memories": tier2_summaries,
            "tier3_event_count": len(event_summaries) if event_summaries else 0,
            "tier3_events": event_summaries if event_summaries else [],
        }

        result = self._call_llm(system_prompt, user_content, temperature=0.3)

        if result:
            result.setdefault("critical_facts", {})
            result.setdefault("reason", "")
        else:
            result = {
                "critical_facts": current_facts,
                "reason": "LLM 调用失败，保持原有 facts",
            }

        return result

    # ============================================================
    # 事件冲突检测（识别气话、情绪化表达）
    # ============================================================

    def detect_emotional_conflicts(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        检测事件中的情绪化表达和潜在冲突

        用于识别：
        1. 气话、情绪化言论
        2. 前后矛盾的陈述
        3. 需要后续验证的言论

        Args:
            events: Tier3 事件列表

        Returns:
            {
                "emotional_events": [
                    {
                        "event_id": "...",
                        "summary": "...",
                        "emotion_type": "anger|frustration|sadness",
                        "is_credible": false  // 是否可信（气话不可信）
                    }
                ],
                "conflicts": [
                    {
                        "description": "用户说'不来了'但之前说'经常来'",
                        "severity": "low|medium|high"
                    }
                ],
                "pending_verifications": [
                    {
                        "claim": "用户说'明天开始减肥'",
                        "verify_after": "2026-04-22"
                    }
                ]
            }
        """
        system_prompt = (
            "你是事件冲突检测器，负责识别情绪化表达和潜在冲突。\n\n"
            "【检测目标】\n"
            "1. 气话、情绪化言论（不可作为事实依据）\n"
            "2. 前后矛盾的陈述（需要进一步验证）\n"
            "3. 冲动性言论（可能是临时决定）\n\n"
            "【情绪化表达识别】\n"
            "- '我不想再认你这个姐姐了' → 气话，is_credible=false\n"
            "- '我讨厌你' → 情绪发泄，is_credible=false\n"
            "- '再也不来了' → 结合上下文，如果是争吵后说的，is_credible=false\n"
            "- '我明天就开始减肥' → 冲动言论，加入 pending_verifications\n\n"
            "【冲突检测】\n"
            "- 用户说'我不吃辣'但之前说'我喜欢川菜' → 记录冲突\n"
            "- 用户说'第一次来'但之前说'我经常来' → 记录冲突\n\n"
            "只输出一个 JSON 对象，格式为：\n"
            "{\n"
            '  "emotional_events": [\n'
            "    {\n"
            '      "event_id": "...",\n'
            '      "summary": "...",\n'
            '      "emotion_type": "anger|frustration|sadness|joy",\n'
            '      "is_credible": false\n'
            "    }\n"
            "  ],\n"
            '  "conflicts": [\n'
            "    {\n"
            '      "description": "...",\n'
            '      "severity": "low|medium|high"\n'
            "    }\n"
            "  ],\n"
            '  "pending_verifications": [\n'
            "    {\n"
            '      "claim": "...",\n'
            '      "verify_after": "YYYY-MM-DD"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        # 构建事件摘要
        event_summaries = []
        for e in events[:30]:
            summary = {
                "event_id": e.get("event_id", ""),
                "time": e.get("start_ts", "")[:16],
                "summary": e.get("summary", ""),
                "dialogue_act": e.get("dialogue_act", "unknown"),
            }
            extra = e.get("extra_slots", {})
            if extra:
                if extra.get("emotion"):
                    summary["emotion"] = extra["emotion"]
            event_summaries.append(summary)

        user_content = {
            "event_count": len(event_summaries),
            "events": event_summaries,
        }

        result = self._call_llm(system_prompt, user_content, temperature=0.3)

        if result:
            result.setdefault("emotional_events", [])
            result.setdefault("conflicts", [])
            result.setdefault("pending_verifications", [])
        else:
            result = {
                "emotional_events": [],
                "conflicts": [],
                "pending_verifications": [],
                "reason": "LLM 调用失败",
            }

        return result


# 全局客户端实例（懒加载）
_client: Optional[CLayerLLMClient] = None


def get_llm_client(model_name: str = "glm-4-flash") -> CLayerLLMClient:
    """获取全局 LLM 客户端实例"""
    global _client
    if _client is None:
        _client = CLayerLLMClient(model_name=model_name)
    return _client
