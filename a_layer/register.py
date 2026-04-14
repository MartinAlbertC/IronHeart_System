#!/usr/bin/env python3
"""
离线人员注册脚本

用法：
  # 注册新人员（人脸 + 声纹）
  python register.py --id zhangsan --name 张三 --faces data/faces/zhangsan/ --voices data/voices/zhangsan/

  # 注册穿戴者
  python register.py --id wearer --name 穿戴者 --faces data/faces/wearer/ --voices data/voices/wearer/ --wearer

  # 查看注册库
  python register.py --list
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from shared.registry import PersonRegistry


def register_faces(registry: PersonRegistry, person_id: str, faces_dir: str):
    import cv2
    import insightface
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name="buffalo_l", providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    face_dir = Path(faces_dir)
    image_files = list(face_dir.glob("*.jpg")) + list(face_dir.glob("*.png")) + list(face_dir.glob("*.jpeg"))

    if not image_files:
        print(f"  [WARN] 未找到图片文件: {faces_dir}")
        return 0

    count = 0
    for img_path in image_files:
        img = cv2.imread(str(img_path))
        if img is None:
            print(f"  [SKIP] 无法读取: {img_path.name}")
            continue

        faces = app.get(img)
        if not faces:
            print(f"  [SKIP] 未检测到人脸: {img_path.name}")
            continue

        # 取置信度最高的人脸
        face = max(faces, key=lambda f: f.det_score)
        quality = float(face.det_score)

        if quality < 0.5:
            print(f"  [SKIP] 人脸质量过低({quality:.2f}): {img_path.name}")
            continue

        import numpy as np
        emb = np.array(face.embedding, dtype=np.float32)
        emb /= (np.linalg.norm(emb) + 1e-8)
        registry.add_face_embedding(person_id, emb, quality)
        count += 1
        print(f"  [OK] 人脸: {img_path.name} (quality={quality:.2f})")

    return count


def register_voices(registry: PersonRegistry, person_id: str, voices_dir: str):
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    import sys
    sys.path.insert(0, str(Path(__file__).parent / "a_layer"))
    from src.audio.audio_embedder import VoiceEmbedder

    embedder = VoiceEmbedder()
    voice_dir = Path(voices_dir)
    audio_files = list(voice_dir.glob("*.wav")) + list(voice_dir.glob("*.mp3")) + list(voice_dir.glob("*.flac"))

    if not audio_files:
        print(f"  [WARN] 未找到音频文件: {voices_dir}")
        return 0

    count = 0
    for audio_path in audio_files:
        try:
            import librosa
            audio, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        except Exception as e:
            print(f"  [SKIP] 无法读取: {audio_path.name} ({e})")
            continue

        if len(audio) < 16000:  # 少于 1 秒跳过
            print(f"  [SKIP] 音频过短: {audio_path.name}")
            continue

        result = embedder.extract(audio)
        emb = np.array(result["vector"], dtype=np.float32)
        registry.add_voice_embedding(person_id, emb, quality=0.8)
        count += 1
        print(f"  [OK] 声纹: {audio_path.name}")

    return count


def main():
    parser = argparse.ArgumentParser(description="IronHeart 人员注册工具")
    parser.add_argument("--id", help="人员 ID（唯一标识）")
    parser.add_argument("--name", help="显示名称")
    parser.add_argument("--faces", help="人脸图片目录")
    parser.add_argument("--voices", help="声音音频目录")
    parser.add_argument("--wearer", action="store_true", help="标记为穿戴者")
    parser.add_argument("--list", action="store_true", help="列出所有注册人员")
    args = parser.parse_args()

    registry = PersonRegistry()

    if args.list:
        persons = registry.list_persons()
        if not persons:
            print("注册库为空")
            return
        print(f"\n{'ID':<15} {'姓名':<12} {'人脸样本':>6} {'声纹样本':>6} {'穿戴者':>6}")
        print("-" * 50)
        for p in persons:
            wearer_mark = "★" if p["is_wearer"] else ""
            print(f"{p['person_id']:<15} {p['display_name']:<12} {p['face_samples']:>6} {p['voice_samples']:>6} {wearer_mark:>6}")
        return

    if not args.id or not args.name:
        parser.print_help()
        sys.exit(1)

    print(f"\n注册人员: {args.name} (ID: {args.id})")
    registry.register_person(args.id, args.name, is_wearer=args.wearer)

    face_count = 0
    voice_count = 0

    if args.faces:
        print(f"\n处理人脸图片: {args.faces}")
        face_count = register_faces(registry, args.id, args.faces)

    if args.voices:
        print(f"\n处理声音文件: {args.voices}")
        voice_count = register_voices(registry, args.id, args.voices)

    print(f"\n注册完成: {args.name} | 人脸样本={face_count} | 声纹样本={voice_count}")
    if args.wearer:
        print("  ★ 已标记为穿戴者")


if __name__ == "__main__":
    main()
