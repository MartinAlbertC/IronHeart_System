"""场景描述生成模块（Florence-2 DETAILED_CAPTION）"""
import os
import cv2
import numpy as np

# 禁用 Flash Attention（CPU 环境不支持）
os.environ['USE_FLASH_ATTENTION'] = 'false'
os.environ['USE_FLASH_ATTENTION_2'] = 'false'


class SceneClassifier:
    """基于 Florence-2 的场景描述生成器。

    使用 <DETAILED_CAPTION> 任务对完整帧生成自由文本描述，
    如 "A group of people sitting around a conference table in a meeting room."
    """

    def __init__(self, model_dir: str, device: str = "cpu"):
        from modelscope import AutoModelForCausalLM, AutoProcessor
        import torch

        self.device = device
        self.model = AutoModelForCausalLM.from_pretrained(
            model_dir, trust_remote_code=True, attn_implementation='eager'
        ).to(device)
        self.model.eval()
        self.processor = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
        self._task = "<DETAILED_CAPTION>"

    def describe(self, frame: np.ndarray) -> str:
        """对完整帧生成场景描述。

        Args:
            frame: BGR 格式 numpy 数组（来自 OpenCV）

        Returns:
            描述字符串，如 "A group of people sitting around a table..."
        """
        import torch
        from PIL import Image

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)

        inputs = self.processor(
            text=self._task,
            images=pil_img,
            return_tensors="pt"
        ).to(self.device)

        with torch.no_grad():
            generated_ids = self.model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=128,
                num_beams=3,
                do_sample=False,
                early_stopping=True,
                use_cache=False,
            )

        generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        parsed = self.processor.post_process_generation(
            generated_text,
            task=self._task,
            image_size=(pil_img.width, pil_img.height)
        )
        return parsed.get(self._task, "").strip()
