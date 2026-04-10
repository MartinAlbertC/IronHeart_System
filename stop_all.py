#!/usr/bin/env python3
"""停止所有 IranHeart 系统进程"""
import subprocess
import sys


def stop_all():
    print("正在查找 IranHeart 相关进程...")

    # 要杀掉的进程关键词
    targets = [
        ("broker.py",      "Broker (MQ)"),
        ("a_layer/run.py", "A 层"),
        ("b_layer/run.py", "B 层"),
        ("c_layer/run.py", "C 层"),
        ("d_layer/run.py", "D 层"),
        ("mqConsumer.js",  "E 层"),
    ]

    killed = 0
    for keyword, label in targets:
        try:
            result = subprocess.run(
                ["wmic", "process", "where",
                 f"commandline like '%{keyword}%'",
                 "get", "processid"],
                capture_output=True, text=True, timeout=10,
            )
            pids = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.isdigit():
                    pids.append(line)

            if pids:
                for pid in pids:
                    subprocess.run(["taskkill", "/PID", pid, "/F"],
                                   capture_output=True, timeout=5)
                print(f"  [{label}] 已停止 PID={', '.join(pids)}")
                killed += len(pids)
            else:
                print(f"  [{label}] 未运行")
        except Exception as e:
            print(f"  [{label}] 查找失败: {e}")

    if killed:
        print(f"\n共停止 {killed} 个进程")
    else:
        print("\n没有找到运行中的 IranHeart 进程")


if __name__ == "__main__":
    stop_all()
