"""场景描述生成模块（moondream2）"""
import os
import cv2
import numpy as np

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


class SceneClassifier:
    """基于 moondream2 的场景描述生成器。"""

    def __init__(self, model_dir: str = None, device: str = "cuda"):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch

        self.device = device
        model_id = "vikhyatk/moondream2"
        revision = "2025-01-09"

        self.model = AutoModelForCausalLM.from_pretrained(
            model_id, revision=revision, trust_remote_code=True,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        ).to(device)
        self.model.eval()
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision)

    def describe(self, frame: np.ndarray) -> str:
        from PIL import Image
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        enc = self.model.encode_image(pil_img)
        return self.model.answer_question(enc, "Describe this scene briefly.", self.tokenizer)
