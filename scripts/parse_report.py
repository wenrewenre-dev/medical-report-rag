# scripts/parse_report.py —— 第5步：解析报告 → 定位知识库 → 标记异常
# 设计思想：数值提取用确定性代码（正则），不用LLM——免费、瞬间、100%可复现
import json
import re

KB_PATH = "data/kb.json"
NUM = r"\d+(?:\.\d+)?"  # 整数或小数

SAMPLE_REPORT = """检验报告单
姓名：张三  性别：男  年龄：35
标本：静脉血
--------------------------------------
WBC  白细胞计数        4.2   ×10^9/L   3.5-9.5
HGB  血红蛋白          112   g/L       130-175
MCV  平均红细胞体积     86    fL        82-100
MCH  平均血红蛋白量     22    pg        27-34
MCHC 平均血红蛋白浓度   305   g/L       316-354
PLT  血小板计数        210   ×10^9/L   125-350
K    血清钾            3.1   mmol/L    3.5-5.3
Na   血清钠            141   mmol/L    137-147
GLU  空腹血糖          6.8   mmol/L    3.9-6.1
ALT  丙氨酸氨基转移酶   65    U/L       9-50
Cr   血肌酐            88    μmol/L    57-111
UA   尿酸              440   μmol/L    208-428
TC   总胆固醇          6.2   mmol/L    2.8-5.7
TG   甘油三酯          1.4   mmol/L    0.4-1.7
--------------------------------------
"""

def load_lookup():
    """知识库 → 查找表{关键词: 条目}。关键词 = 项目名+缩写+别名"""
    with open(KB_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)
    lookup = {}
    for it in items:
        keys = [it["name"]] + it.get("abbr", []) + it.get("aliases", [])
        for k in keys:
            lookup[k.strip().lower()] = it
    return items, lookup

def find_item(line, lookup):
    """识别该行属于哪个项目。按关键词长度降序尝试，
    避免'血糖'抢先命中了'空腹血糖'所在的行"""
    low = line.lower()
    for key in sorted(lookup, key=len, reverse=True):
        if key not in low:
            continue
        # 纯字母缩写（K、Cr、Na）要求两侧是非字母，防止误匹配到别的单词
        if key.isascii() and re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", low):
            return lookup[key]
        if not key.isascii():
            return lookup[key]
    return None

def parse_line(line, lookup):
    item = find_item(line, lookup)
    if item is None:
        return None
    m = re.search(NUM, line)          # 行内第一个数字 = 检验数值
    if not m:
        return None
    value = float(m.group())
    # 报告上印的参考范围（兼容 3.5-9.5 / 3.5～9.5 等写法）
    m2 = re.search(rf"({NUM})\s*[-~—～]\s*({NUM})", line)
    printed = (float(m2.group(1)), float(m2.group(2))) if m2 else None
    return {"item": item, "value": value, "printed": printed}

def pick_kb_range(item, report_text):
    """知识库里同项目可能有男女多套区间：优先按报告里的性别匹配"""
    rs = item["reference_ranges"]
    if len(rs) == 1:
        return rs[0]
    if re.search(r"性别[:：]?\s*女", report_text):
        for r in rs:
            if "女" in r["population"]:
                return r
    if re.search(r"性别[:：]?\s*男", report_text):
        for r in rs:
            if "男" in r["population"]:
                return r
    return rs[0]

def judge(entry, report_text):
    item, v = entry["item"], entry["value"]
    # 判定用哪套范围？报告印的优先（各家医院方法学不同，范围略有差异）；
    # 没印再用知识库的（按性别挑选）
    if entry["printed"]:
        lo, hi = entry["printed"]
        src = "报告"
    else:
        r = pick_kb_range(item, report_text)
        lo, hi, src = r["low"], r["high"], "知识库"

    flag, arrow, icon = "正常", "", "✓"
    if v < lo:
        flag, arrow, icon = "偏低", "↓", "⚠️"
    elif v > hi:
        flag, arrow, icon = "偏高", "↑", "⚠️"

    critical = None
    if item.get("critical_low") is not None and v <= item["critical_low"]:
        critical = f"危急低值 {item['critical_low']}"
    if item.get("critical_high") is not None and v >= item["critical_high"]:
        critical = f"危急高值 {item['critical_high']}"
    return {"lo": lo, "hi": hi, "flag": flag, "arrow": arrow,
            "icon": icon, "critical": critical, "src": src}

def main():
    _, lookup = load_lookup()
    report = SAMPLE_REPORT   # 以后可换成让用户粘贴自己的报告
    parsed, skipped = [], []

    for line in report.splitlines():
        line = line.strip()
        if not line or set(line) <= set("-— "):        # 跳过空行和分隔线
            continue
        entry = parse_line(line, lookup)
        if entry:
            parsed.append(entry)
        elif re.search(rf"{NUM}\s*[-~—～]\s*{NUM}", line):
            skipped.append(line)   # 像结果行但认不出 → 未收录

    print("📋 解析结果：")
    abnormals = []
    for e in parsed:
        j = judge(e, report)
        out = (f"   {j['icon']} {e['item']['name']}：{e['value']} {e['item']['unit']}"
               f"（范围 {j['lo']}-{j['hi']}，来源{j['src']}）→ {j['flag']} {j['arrow']}")
        if j["critical"]:
            out += f"  🚨 达到{j['critical']}！"
        print(out)
        if j["flag"] != "正常":
            abnormals.append((e, j))
    for s in skipped:
        print(f"   ❓ 知识库未收录，已跳过：{s}")

    print(f"\n🎯 小计：识别 {len(parsed)} 项，异常 {len(abnormals)} 项，未收录 {len(skipped)} 项")
    if abnormals:
        print("   异常清单：" + "、".join(
            f"{e['item']['name']}{j['arrow']}" for e, j in abnormals))

if __name__ == "__main__":
    main()
