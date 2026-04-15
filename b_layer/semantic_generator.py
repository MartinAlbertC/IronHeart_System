import json
import requests
import logging
from typing import List, Dict

logger = logging.getLogger("IranHeart.b_layer")


class SemanticGenerator:
    def __init__(self, config: Dict):
        self.api_url = config["llm_api_url"]
        self.api_key = config["llm_api_key"]
        self.model = config["model"]
        self.temperature = config["temperature"]
        self.max_tokens = config["max_tokens"]
        self.timeout = config["timeout"]

    def generate(
        self, window_events: List[Dict], context: Dict, history: list = None
    ) -> Dict:
        if not self.api_url or not self.api_key:
            return {"summary": "事件聚合", "dialogue_act": "unknown"}

        prompt = self._build_prompt(window_events, context, history or [])

        for attempt in range(3):
            try:
                response = requests.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                    },
                    timeout=self.timeout,
                )

                if response.status_code != 200:
                    print(f"API错误 {response.status_code}: {response.text[:200]}")
                    raise Exception(f"API returned {response.status_code}")

                result = response.json()
                message = result["choices"][0]["message"]
                content = message.get("content") or message.get("reasoning_content", "")

                # Extract JSON from markdown code block
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                return json.loads(content)
            except Exception as e:
                print(f"LLM调用失败 (尝试 {attempt + 1}/3): {str(e)[:100]}")
                if attempt == 2:
                    return {"summary": "事件聚合", "dialogue_act": "unknown"}

        return {"summary": "事件聚合", "dialogue_act": "unknown"}

    def _build_prompt(self, events: List[Dict], context: Dict, history: list) -> str:
        # 上下文信息
        history_str = ""
        if history:
            lines = [f"{i + 1}. {s}" for i, s in enumerate(history)]
            history_str = "\n".join(lines)

        # 场景信息
        scene_parts = []
        for e in events:
            if e.get("event_type") == "scene_detection":
                label = e["payload"].get("scene_label", "")
                objects = e["payload"].get("objects", [])
                if label:
                    scene_parts.append(label)
                if objects:
                    scene_parts.append(f"附近有：{', '.join(objects)}")
        scene_str = "，".join(scene_parts) if scene_parts else "（未知）"

        # 按 alias 聚合：收集每个 alias 的 has_face / speech_texts
        alias_order = []
        alias_data = {}  # alias -> {'has_face': bool, 'has_voice': bool, 'texts': []}
        for e in sorted(events, key=lambda x: x["time"]["start_ts"]):
            alias = e.get("resolved_alias", "unknown")
            if alias not in alias_data:
                alias_order.append(alias)
                alias_data[alias] = {"has_face": False, "has_voice": False, "texts": []}
            if e["event_type"] == "face_detection":
                alias_data[alias]["has_face"] = True
            elif e["event_type"] == "speech_segment":
                alias_data[alias]["has_voice"] = True
                text = e["payload"].get("text", "").strip()
                if text:
                    alias_data[alias]["texts"].append(text)

        # 构建人物信息段落
        person_lines = []
        for i, alias in enumerate(alias_order, 1):
            d = alias_data[alias]
            if d["has_voice"]:
                speech = "".join(d["texts"])
                prefix = "" if d["has_face"] else "<人脸未出现在视野> "
                person_lines.append(f"{i}. {alias} {prefix}说：{speech}")
            else:
                person_lines.append(f"{i}. {alias} 出现人脸，没有说话")

        persons_str = "\n".join(person_lines)

        prompt = f"""分析以下场景，生成语义事件摘要。
{f"【上下文信息】{chr(10)}{history_str}{chr(10)}" if history_str else ""}
【场景信息】
{scene_str}

【人物信息】
{persons_str}

输出JSON格式：
{{"summary": "用一句话概括当前场景和对话内容", "dialogue_act": "statement/request/promise/complaint/greeting/status_update/unknown"}}"""

        logger.info(f"\n{'=' * 60}\n[LLM PROMPT]\n{prompt}\n{'=' * 60}")
        # print(f"\n{'='*60}\n[LLM PROMPT]\n{prompt}\n{'='*60}", flush=True)
        return prompt
