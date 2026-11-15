# scripts/parse_report.py —— 第5步：解析报告 → 定位知识库 → 标记异常
# 设计思想：数值提取用确定性代码（正则），不用LLM——免费、瞬间、100%可复现
#
# 两个容易出错的地方，这里都按知识库里的元数据来判，不靠猜：
#   1. 单位：报告用 g/dL、知识库用 g/L 时先换算，否则 13.5 g/dL（=135 g/L，正常）会被判成"偏低"
#   2. 危急值：知识库里按人群分条（成人/儿童/新生儿/抗凝状态），要挑最贴合这个患者的那条
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


# ---------- 单位换算 ----------
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


def normalize_unit(unit: str) -> str:
    """把 ×10⁹/L、×10^9/L、x10*9/L 这些写法统一成可比对的形态"""
    if not unit:
        return ""
    u = unit.translate(_SUPERSCRIPT).lower()
    for ch in ("×", "x", "*", "^", " ", "·"):
        u = u.replace(ch, "")
    return u.replace("μ", "u")


def detect_unit(line: str, item):
    """认出这一行用的单位。只在该条目自己的单位集合里找，避免把别的单位误认进来"""
    norm_line = normalize_unit(line)
    candidates = sorted({item.get("unit") or "",
                         *[c.get("from_unit") or "" for c in item.get("unit_conversions") or []]},
                        key=len, reverse=True)          # 长的优先: g/dL 先于 g/L
    for cand in candidates:
        n = normalize_unit(cand)
        if n and n in norm_line:
            return cand
    return ""


def find_conversion(item, report_unit: str):
    target = normalize_unit(report_unit)
    for conv in item.get("unit_conversions") or []:
        if normalize_unit(conv.get("from_unit") or "") == target:
            return conv
    return None


def convert_to_base(entry, item):
    """报告单位 → 知识库单位。value / printed 一起换算，保证后面比较的是同一把尺子"""
    unit = detect_unit(entry["_line"], item)
    entry["report_unit"] = unit
    entry["raw_value"] = entry["value"]                   # 原始数值, 展示时用
    entry["converted"] = False
    entry["conv_factor"] = 1.0
    if not unit or normalize_unit(unit) == normalize_unit(item.get("unit") or ""):
        return entry
    conv = find_conversion(item, unit)
    factor = conv.get("factor") if conv else None
    if not factor:
        return entry                                      # 认得单位但没有换算规则: 保持原样
    entry["value"] = entry["value"] * float(factor)
    if entry["printed"]:
        entry["printed"] = (entry["printed"][0] * factor, entry["printed"][1] * factor)
    entry["converted"] = True
    entry["conv_factor"] = float(factor)
    return entry


# ---------- 人群匹配 ----------
def _patient_profile(report_text: str):
    """从报告里读性别和年龄（年龄换算成"岁"，方便跟知识库的 age_range 比）"""
    if re.search(r"性别[:：]?\s*女", report_text):
        sex = "女"
    elif re.search(r"性别[:：]?\s*男", report_text):
        sex = "男"
    else:
        sex = None
    m = re.search(r"年龄[:：]?\s*(\d+)\s*(岁|天|月)?", report_text)
    if not m:
        return sex, None
    n, unit = float(m.group(1)), (m.group(2) or "岁")
    if unit == "天":
        return sex, n / 365.0
    if unit == "月":
        return sex, n / 12.0
    return sex, n


def _age_hit(age_range, age_years):
    """返回 True/False；不知道年龄时返回 None（无法判断，不算矛盾）"""
    if not age_range or age_years is None:
        return None
    lo, hi, unit = age_range.get("min"), age_range.get("max"), age_range.get("unit") or "岁"
    if unit == "天":
        lo = lo / 365.0 if lo is not None else None
        hi = hi / 365.0 if hi is not None else None
    elif unit == "月":
        lo = lo / 12.0 if lo is not None else None
        hi = hi / 12.0 if hi is not None else None
    if lo is not None and age_years < lo:
        return False
    if hi is not None and age_years >= hi:
        return False
    return True


# 人群标签里的特殊语境 → 报告里出现对应词时优先选它
_SPECIAL = {"孕": ("孕", "妊娠"), "新生儿": ("新生儿",), "儿童": ("儿童", "小儿"),
            "老年": ("老年",), "华法林": ("华法林",), "肝素": ("肝素",),
            "术前": ("术前", "出血")}


def pick_population(candidates, report_text: str):
    """在参考区间/危急值列表里挑最贴合这个患者的一条。
    排序依据: 性别命中 > 年龄命中 > 人群标签命中；明确不符的直接排除；全不符就退回第一条。"""
    cands = candidates or []
    if not cands:
        return None
    sex, age_years = _patient_profile(report_text)
    best, best_score = None, None
    for cand in cands:
        c_sex = cand.get("sex")
        if c_sex and sex and c_sex != sex:
            continue                                      # 性别明确不符
        if _age_hit(cand.get("age_range"), age_years) is False:
            continue                                      # 年龄明确不符
        score = 0
        if c_sex and sex == c_sex:
            score += 4
        if _age_hit(cand.get("age_range"), age_years):
            score += 3
        if cand.get("age_range") and age_years is None:
            score -= 1                                    # 带年龄约束但不知道年龄, 降级
        label = str(cand.get("population") or "")
        for key, words in _SPECIAL.items():
            if key in label and any(w in report_text for w in words):
                score += 2
        if best_score is None or score > best_score:
            best, best_score = cand, score
    return best or cands[0]                                # 都不匹配 → 退回首条(通常是成人通用)


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
    entry = {"item": item, "value": value, "printed": printed, "_line": line}
    entry = convert_to_base(entry, item)
    entry.pop("_line", None)                              # 行文本只用来认单位, 不往下游传
    return entry


def judge(entry, report_text):
    item, v = entry["item"], entry["value"]
    # 判定用哪套范围？报告印的优先（各家医院方法学不同，范围略有差异）；
    # 没印再用知识库的（按性别/年龄/人群挑）
    if entry["printed"]:
        lo, hi = entry["printed"]
        src = "报告"
    else:
        r = pick_population(item["reference_ranges"], report_text)
        lo, hi, src = r["low"], r["high"], "知识库"

    flag, arrow, icon = "正常", "", "✓"
    if v < lo:
        flag, arrow, icon = "偏低", "↓", "⚠️"
    elif v > hi:
        flag, arrow, icon = "偏高", "↑", "⚠️"

    # 危急值：知识库里按人群分条（成人/儿童/新生儿/抗凝状态），挑最贴合的那条再比
    crit = pick_population(item.get("critical_values") or [], report_text)
    critical = critical_action = critical_pop = None
    if crit:
        c_low, c_high = crit.get("critical_low"), crit.get("critical_high")
        if c_low is not None and v <= c_low:
            critical = f"危急低值 {c_low}"
        elif c_high is not None and v >= c_high:
            critical = f"危急高值 {c_high}"
        if critical:
            critical_action, critical_pop = crit.get("action"), crit.get("population")

    return {"lo": lo, "hi": hi, "flag": flag, "arrow": arrow,
            "icon": icon, "critical": critical,
            "critical_action": critical_action, "critical_population": critical_pop,
            "src": src,
            "converted": entry.get("converted", False),
            "raw_value": entry.get("raw_value", entry["value"]),
            "report_unit": entry.get("report_unit", ""),
            "conv_factor": entry.get("conv_factor", 1.0)}


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
