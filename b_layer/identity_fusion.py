"""
身份融合模块：双模态 alias 融合

策略：
- face alias + voice alias 一致 → 直接使用
- 只有一个模态有 alias → 使用该模态
- 两者冲突 → 取置信度更高的，记录冲突供后续合并
"""
from typing import Optional, Tuple, Dict


class IdentityFusion:

    def fuse(self,
             face_alias: Optional[str], face_conf: float,
             voice_alias: Optional[str], voice_conf: float) -> Tuple[str, str]:
        """
        融合人脸和声纹 alias。

        Returns:
            (resolved_alias, modality_used)
        """
        if face_alias and voice_alias:
            if face_alias == voice_alias:
                return face_alias, "face+voice"
            # 冲突：取置信度高的
            if face_conf >= voice_conf:
                return face_alias, "face"
            else:
                return voice_alias, "voice"

        if face_alias:
            return face_alias, "face"
        if voice_alias:
            return voice_alias, "voice"

        return "unknown", "none"

    def fuse_event(self, event: Dict) -> Dict:
        """
        从事件 payload 中提取 alias 信息并融合，
        将 resolved_alias 和 modality_used 写回事件。
        """
        payload = event.get("payload", {})
        face_alias = payload.get("alias") if event.get("event_type") == "face_detection" else None
        voice_alias = payload.get("alias") if event.get("event_type") == "speech_segment" else None

        face_conf = event.get("confidence", {}).get("quality_score", 0.5)
        voice_conf = 0.5  # 声纹匹配暂无置信度字段，默认 0.5

        alias, modality = self.fuse(face_alias, face_conf, voice_alias, voice_conf)
        event["resolved_alias"] = alias
        event["modality_used"] = modality
        return event
