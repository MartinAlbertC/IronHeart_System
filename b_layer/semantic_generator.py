import json
import requests
from typing import List, Dict

class SemanticGenerator:
    def __init__(self, config: Dict):
        self.api_url = config['llm_api_url']
        self.api_key = config['llm_api_key']
        self.model = config['model']
        self.temperature = config['temperature']
        self.max_tokens = config['max_tokens']
        self.timeout = config['timeout']

    def generate(self, window_events: List[Dict], context: Dict) -> Dict:
        if not self.api_url or not self.api_key:
            return {
                'summary': '事件聚合',
                'dialogue_act': 'unknown'
            }

        prompt = self._build_prompt(window_events, context)

        for attempt in range(3):
            try:
                response = requests.post(
                    self.api_url,
                    headers={'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'},
                    json={'model': self.model, 'messages': [{'role': 'user', 'content': prompt}],
                          'temperature': self.temperature, 'max_tokens': self.max_tokens},
                    timeout=self.timeout
                )

                if response.status_code != 200:
                    print(f"API错误 {response.status_code}: {response.text[:200]}")
                    raise Exception(f"API returned {response.status_code}")

                result = response.json()
                message = result['choices'][0]['message']
                content = message.get('content') or message.get('reasoning_content', '')

                # Extract JSON from markdown code block
                if '```json' in content:
                    content = content.split('```json')[1].split('```')[0].strip()
                elif '```' in content:
                    content = content.split('```')[1].split('```')[0].strip()

                return json.loads(content)
            except Exception as e:
                print(f"LLM调用失败 (尝试 {attempt+1}/3): {str(e)[:100]}")
                if attempt == 2:
                    return {'summary': '事件聚合', 'dialogue_act': 'unknown'}

        return {'summary': '事件聚合', 'dialogue_act': 'unknown'}

    def _build_prompt(self, events: List[Dict], context: Dict) -> str:
        event_desc = []
        speech_texts = []
        for e in events:
            ts = e['time']['start_ts']
            if e['event_type'] == 'face_detection' and 'resolved_alias' in e:
                event_desc.append(f"- {ts}: 检测到{e['resolved_alias']}的人脸")
            elif e['event_type'] == 'speech_segment':
                text = e['payload'].get('text', '')
                alias = e.get('resolved_alias', '未知')
                event_desc.append(f"- {ts}: {alias}说话: {text}")
                if text:
                    speech_texts.append(text)

        return f"""分析以下对话场景，生成语义事件摘要。

场景：{context['scene_label']}
人物：{', '.join(context['active_persons'])}

事件序列：
{chr(10).join(event_desc)}

对话内容：{' '.join(speech_texts)}

根据对话内容判断dialogue_act类型：
- request: 请求、询问、寻求帮助
- promise: 承诺、保证、答应做某事
- complaint: 抱怨、不满、负面情绪
- greeting: 问候、打招呼、告别
- status_update: 陈述事实、汇报状态、描述情况
- unknown: 无法判断

输出JSON格式：
{{"summary": "用一句话概括对话内容和意图", "dialogue_act": "选择最合适的类型"}}"""
