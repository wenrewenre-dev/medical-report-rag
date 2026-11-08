# scripts/append_batch.py
# -*- coding: utf-8 -*-
"""把新批次 JSON 数组合并进 kb.json，自动按 id 去重、排序、备份
用法: python scripts/append_batch.py data/batch2.json
"""
import json, sys
from pathlib import Path

def load_json_array(path):
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"✗ {path} 的根节点必须是数组 [ ]")
    return data

def main():
    kb_path = Path("data/kb.json")
    batch_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/batch2.json")
    if not batch_path.exists():
        raise SystemExit(f"✗ 找不到批次文件：{batch_path}")

    kb = load_json_array(kb_path)
    batch = load_json_array(batch_path)

    existing_ids = {it["id"] for it in kb if isinstance(it, dict) and "id" in it}
    added, skipped = 0, 0
    for it in batch:
        if not isinstance(it, dict) or "id" not in it:
            print(f"跳过非法条目: {str(it)[:60]}")
            skipped += 1
        elif it["id"] in existing_ids:
            print(f"跳过重复 id {it['id']}（{it.get('name','?')}）")
            skipped += 1
        else:
            kb.append(it)
            existing_ids.add(it["id"])
            added += 1

    kb.sort(key=lambda x: x.get("id", 0))

    bak = kb_path.with_suffix(".json.bak")
    bak.write_text(kb_path.read_text(encoding="utf-8"), encoding="utf-8")
    kb_path.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✓ 合并完成：新增 {added} 条，跳过 {skipped} 条，当前共 {len(kb)} 条")
    print(f"  原文件已备份为 {bak.name}")

if __name__ == "__main__":
    main()
