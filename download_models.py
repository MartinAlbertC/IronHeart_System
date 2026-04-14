#!/usr/bin/env python3
"""
IronHeart 模型文件下载脚本
运行: python download_models.py
"""
import os
import urllib.request
import hashlib
import sys
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"

# 所有需要下载的模型文件
# 格式: (目标路径, 下载URL, 文件大小提示)
MODELS = [
    # ── Florence-2 场景描述模型 (~890MB) ──
    (
        "AI-ModelScope/Florence-2-base/model.safetensors",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/model.safetensors",
        "~442MB",
    ),
    (
        "AI-ModelScope/Florence-2-base/pytorch_model.bin",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/pytorch_model.bin",
        "~443MB",
    ),
    (
        "AI-ModelScope/Florence-2-base/config.json",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/config.json",
        "~1KB",
    ),
    (
        "AI-ModelScope/Florence-2-base/configuration_florence2.py",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/configuration_florence2.py",
        "~15KB",
    ),
    (
        "AI-ModelScope/Florence-2-base/modeling_florence2.py",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/modeling_florence2.py",
        "~125KB",
    ),
    (
        "AI-ModelScope/Florence-2-base/processing_florence2.py",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/processing_florence2.py",
        "~48KB",
    ),
    (
        "AI-ModelScope/Florence-2-base/preprocessor_config.json",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/preprocessor_config.json",
        "~1KB",
    ),
    (
        "AI-ModelScope/Florence-2-base/tokenizer.json",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/tokenizer.json",
        "~1.3MB",
    ),
    (
        "AI-ModelScope/Florence-2-base/tokenizer_config.json",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/tokenizer_config.json",
        "~1KB",
    ),
    (
        "AI-ModelScope/Florence-2-base/vocab.json",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/vocab.json",
        "~1.1MB",
    ),
    (
        "AI-ModelScope/Florence-2-base/special_tokens_map.json",
        "https://hf-mirror.com/microsoft/Florence-2-base/resolve/main/special_tokens_map.json",
        "~1KB",
    ),

    # ── Wespeaker 声纹编码模型 (~26MB) ──
    (
        "wespeaker/wespeaker-cnceleb-resnet34-LM/cnceleb_resnet34_LM.onnx",
        "https://hf-mirror.com/westlake-repl/SaSpeaker/resolve/main/wespeaker-cnceleb-resnet34-LM/cnceleb_resnet34_LM.onnx",
        "~26MB",
    ),
    (
        "wespeaker/wespeaker-cnceleb-resnet34-LM/config.yaml",
        "https://hf-mirror.com/westlake-repl/SaSpeaker/resolve/main/wespeaker-cnceleb-resnet34-LM/config.yaml",
        "~2KB",
    ),
]

# YOLO 模型（项目根目录）
ROOT_MODELS = [
    (
        "yolo12n.pt",
        "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo12n.pt",
        "~5.4MB",
    ),
    (
        "yolo26n.pt",
        "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo26n.pt",
        "~5.3MB",
    ),
    (
        "yolo26n-cls.pt",
        "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo26n-cls.pt",
        "~5.6MB",
    ),
]


def download_file(url: str, dest: Path, size_hint: str):
    """下载文件，显示进度条"""
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        print(f"  [SKIP] {dest} (already exists)")
        return True

    print(f"  [DOWN] {dest.name} ({size_hint}) ...")
    try:
        urllib.request.urlretrieve(url, str(dest), reporthook=lambda n, b, total: None)
        print(f"  [ OK ] {dest.name}")
        return True
    except Exception as e:
        print(f"  [FAIL] {dest.name}: {e}")
        if dest.exists():
            dest.unlink()
        return False


def main():
    total = len(MODELS) + len(ROOT_MODELS)
    print(f"IronHeart Model Downloader — {total} files to download\n")

    root = Path(__file__).parent
    failed = []

    # models/ 目录下的文件
    for rel_path, url, size_hint in MODELS:
        dest = MODELS_DIR / rel_path
        if not download_file(url, dest, size_hint):
            failed.append(str(dest))

    # 根目录下的 YOLO 模型
    for rel_path, url, size_hint in ROOT_MODELS:
        dest = root / rel_path
        if not download_file(url, dest, size_hint):
            failed.append(str(dest))

    # 复制 botsort_custom.yaml（已在仓库中，无需下载）
    yaml_src = root / "models" / "botsort_custom.yaml"
    if not yaml_src.exists():
        print(f"\n  [WARN] {yaml_src} not found (should be in repo)")

    print()
    if failed:
        print(f"FAILED: {len(failed)} files could not be downloaded:")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All models downloaded successfully!")
        print("\nNOTE: FunASR (SenseVoiceSmall) model will be auto-downloaded on first run.")


if __name__ == "__main__":
    main()
