# scripts/validate_kb.py
# -*- coding: utf-8 -*-
"""检验知识库 JSON 校验器（健壮版）
用法: python scripts/validate_kb.py [path]   # 默认 data/kb.json
"""
import json, re, sys
from pathlib import Path

# 反引号用 chr(96) 运行时构造，避免源码里出现字面三连反引号
FENCE = chr(96) * 3

def read_text_smart(path: Path) -> str:
    raw = path.read_bytes()
    if not raw:
        raise ValueError("文件是空的（0 字节），检查是否保存成功/路径是否正确")
    if raw.startswith(b"\xef\xbb\xbf"):
        print("[提示] 检测到 UTF-8 BOM，已自动跳过")
        return raw[3:].decode("utf-8")
    if raw.startswith(b"\xff\xfe"):
        print("[提示] 检测到 UTF-16 LE（常见于 PowerShell 的 > 重定向），已自动转码")
        return raw.decode("utf-16")
    if raw.startswith(b"\xfe\xff"):
        print("[提示] 检测到 UTF-16 BE，已自动转码")
        return raw.decode("utf-16-be")
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            if enc == "gbk":
                print(f"[提示] 文件不是 UTF-8，已按 {enc} 解码，建议用 VS Code 另存为 UTF-8")
            return text
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请用 VS Code 另存为 UTF-8（无 BOM）")

def strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith(FENCE):
        print("[提示] 检测到 markdown 代码围栏，已自动剥离")
        t = re.sub(r"^" + FENCE + r"[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*" + FENCE + r"$", "", t)
    return t.strip()

def precheck(text: str):
    problems = []
    for i, line in enumerate(text.splitlines(), 1):
        for ch in ("\u201c", "\u201d", "\u2018", "\u2019"):
            if ch in line:
                problems.append(f"  第{i}行：出现中文引号 {ch}，应改为英文双引号")
    for m in re.finditer(r",(\s*[}\]])", text):
        line = text.count("\n", 0, m.start()) + 1
        problems.append(f"  第{line}行：}}或]前有多余逗号")
    return problems

def show_context(text: str, pos: int, span: int = 60):
    line = text.count("\n", 0, pos) + 1
    col = pos - (text.rfind("\n", 0, pos) + 1) + 1
    s, e = max(0, pos - span // 2), min(len(text), pos + span)
    print(f"  位置：第 {line} 行，第 {col} 列")
    print(f"  上下文：{text[s:e]!r}")

def check_schema(data):
    errs = []
    if not isinstance(data, list):
        return ["根节点必须是数组 [ ]"]
    if len(data) < 10 or len(data) > 40:
        errs.append(f"条目数={len(data)}，预期 10–40")
    ids = set()
    required = ["id", "name", "abbr", "aliases", "category", "unit", "reference_ranges",
                "critical_values", "elevated_meaning", "decreased_meaning",
                "related_diseases", "recheck_advice"]
    for i, item in enumerate(data, 1):
        tag = f"第{i}条({item.get('name', '?') if isinstance(item, dict) else '?'})"
        if not isinstance(item, dict):
            errs.append(f"{tag}：不是对象")
            continue
        for k in required:
            if k not in item:
                errs.append(f"{tag}：缺少字段 {k}")
        if item.get("id") in ids:
            errs.append(f"{tag}：id 重复")
        ids.add(item.get("id"))
        for k in ("abbr", "aliases", "related_diseases", "related_indicators"):
            v = item.get(k)
            if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
                errs.append(f"{tag}：{k} 应为字符串数组")
        for rr in item.get("reference_ranges") or []:
            for k in ("low", "high"):
                if rr.get(k) is not None and not isinstance(rr[k], (int, float)):
                    errs.append(f"{tag}：reference_ranges.{k} 应为数字，当前是 {rr[k]!r}")
    return errs

def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/kb.json")
    if not path.exists():
        print(f"✗ 文件不存在：{path.resolve()}（检查是否在 report-rag 目录下运行）")
        sys.exit(1)
    print(f"校验文件：{path}（{path.stat().st_size} 字节）")
    try:
        text = read_text_smart(path)
    except ValueError as e:
        print(f"✗ {e}")
        sys.exit(1)
    text = strip_code_fence(text)
    if not text.startswith("["):
        print(f"✗ 文件开头不是数组起始符，而是：{text[:30]!r}")
        print("  大概率复制时把说明文字/代码围栏一起粘进来了，只保留最外层 [ 到 ] 的内容")
        sys.exit(1)
    issues = precheck(text)
    if issues:
        print("⚠ 结构预检发现问题：")
        for p in issues[:10]:
            print(p)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"✗ JSON 语法错误：{e.msg}")
        show_context(text, e.pos)
        sys.exit(1)
    errs = check_schema(data)
    if errs:
        print("⚠ JSON 语法通过，但 schema 检查发现问题：")
        for e in errs:
            print("  -", e)
        sys.exit(1)
    print(f"✓ 校验通过：共 {len(data)} 条，id 列表 {sorted(x.get('id') for x in data)}")

if __name__ == "__main__":
    main()
