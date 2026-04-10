#!/usr/bin/env python3
"""
手动触发反思：Tier3 → Tier2 长期记忆 + Tier1 用户画像更新

用法:
  python c_layer/reflect.py              # 执行反思
  python c_layer/reflect.py --dry-run    # 仅预览，不写入数据库
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from c_layer.config import PG_CONFIG, TIER3_DB_PATH
from c_layer.night_reflection import NightReflector


def main():
    dry_run = "--dry-run" in sys.argv

    reflector = NightReflector(
        pg_config=PG_CONFIG,
        tier3_db_path=TIER3_DB_PATH,
        user_id="default_user",
    )

    if dry_run:
        print("[DRY RUN] 仅预览，不写入数据库")

    print("反思开始...")
    result = reflector.run(dry_run=dry_run, enable_tier1_update=True)

    print()
    print(json.dumps(result, ensure_ascii=False, indent=2))

    s = result["summary"]
    print()
    print(f"完成: Tier3事件={s['tier3_events']} → Tier2写入={s['tier2_written']} | "
          f"身份标签更新={s['labels_updated']} | 身份重命名={s['names_updated']}")


if __name__ == "__main__":
    main()
