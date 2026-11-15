# scripts/test_parse.py —— 解析层的回归测试（不花钱、不联网）
# 跑法：python scripts/test_parse.py
# 重点：单位换算不能把正常值判成异常；危急值必须按人群挑对阈值；样例报告结果不能变
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_report import (SAMPLE_REPORT, judge, load_lookup, parse_line,
                          pick_population)

_, LOOKUP = load_lookup()
ok = True


def check(name, cond, detail=""):
    global ok
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  {detail}" if detail else ""))
    ok = ok and cond


def one(line, report_text=None):
    """解析一行并判定，返回 (entry, judge 结果)"""
    text = report_text if report_text is not None else line
    e = parse_line(line, LOOKUP)
    return e, judge(e, text)


print("\n[1] 单位换算：报告单位 ≠ 知识库单位")
e, j = one("HGB 血红蛋白 13.5 g/dL", "性别：男")
check("g/dL → g/L 换算正确", abs(e["value"] - 135) < 1e-6, f"{e['value']} g/L")
check("换算后判正常（男性 130-175）", j["flag"] == "正常", f"{j['flag']} {j['lo']}-{j['hi']}")
check("标了 converted 且留了原值", j["converted"] and j["raw_value"] == 13.5 and j["report_unit"] == "g/dL")

e, j = one("HGB 血红蛋白 11.2 g/dL 13.0-17.5", "性别：男")
check("报告自带的范围也跟着换算", (j["lo"], j["hi"]) == (130, 175), f"{j['lo']}-{j['hi']}")
check("换算后判偏低", j["flag"] == "偏低")

e, j = one("GLU 空腹血糖 100 mg/dL 70-110")
check("mg/dL → mmol/L（×0.0555）", abs(e["value"] - 5.55) < 1e-6, f"{e['value']}")
check("范围一起换算", abs(j["lo"] - 3.885) < 1e-6 and abs(j["hi"] - 6.105) < 1e-6)

e, j = one("PLT 血小板计数 210000 /μL")
check("/μL → ×10⁹/L（×0.001）", abs(e["value"] - 210) < 1e-6, f"{e['value']}")

print("\n[2] 单位写法变体：不能误判、也不能误换算")
for line in ["WBC 白细胞计数 5.2 ×10^9/L 3.5-9.5",
             "WBC 白细胞计数 5.2 ×10⁹/L 3.5-9.5",
             "WBC 白细胞计数 5.2 x10*9/L 3.5-9.5"]:
    e, j = one(line)
    check(f"上标写法等价: {line.split()[-2]}", not e["converted"] and abs(e["value"] - 5.2) < 1e-6,
          f"converted={e['converted']}")

e, j = one("K 血清钾 3.1 mmol/L 3.5-5.3")
check("同单位不换算", not e["converted"] and e["value"] == 3.1)

print("\n[3] 危急值：按人群挑阈值")
e, j = one("K 血清钾 2.2 mmol/L 3.5-5.3", "性别：男 年龄：35")
check("低钾危急值触发", j["critical"] == "危急低值 2.5", str(j["critical"]))
check("带处置建议", bool(j["critical_action"]) and "心电监护" in (j["critical_action"] or ""))
check("标了人群", j["critical_population"] == "成人", str(j["critical_population"]))

e, j = one("K 血清钾 6.8 mmol/L 3.5-5.3", "性别：男 年龄：35")
check("高钾危急值触发", j["critical"] == "危急高值 6.5", str(j["critical"]))

e, j = one("K 血清钾 3.1 mmol/L 3.5-5.3", "性别：男 年龄：35")
check("未达阈值不报危急", j["critical"] is None)

e, j = one("HGB 血红蛋白 45 g/L 130-175", "性别：男 年龄：35")
check("血红蛋白危急低值", j["critical"] == "危急低值 50", str(j["critical"]))

print("\n[4] 人群匹配：儿童/新生儿/性别")
e, j = one("K 血清钾 5.4 mmol/L", "性别：男 年龄：5")
check("儿童用 3.5-5.5 区间 → 正常", j["flag"] == "正常" and j["lo"] == 3.5 and j["hi"] == 5.5,
      f"{j['flag']} {j['lo']}-{j['hi']}")
e, j = one("K 血清钾 5.4 mmol/L", "性别：男 年龄：35")
check("成人用 3.5-5.3 区间 → 偏高", j["flag"] == "偏高" and j["hi"] == 5.3,
      f"{j['flag']} {j['lo']}-{j['hi']}")

e, j = one("PLT 血小板计数 90 ×10^9/L", "性别：女 年龄：10天")
check("新生儿危急值（100）", j["critical"] == "危急低值 100" and j["critical_population"] == "新生儿",
      f"{j['critical']} / {j['critical_population']}")

e, j = one("HGB 血红蛋白 120 g/L", "性别：女 年龄：35")
check("女性用 115-150 → 正常", j["flag"] == "正常", f"{j['flag']} {j['lo']}-{j['hi']}")
e, j = one("HGB 血红蛋白 120 g/L", "性别：男 年龄：35")
check("男性用 130-175 → 偏低", j["flag"] == "偏低", f"{j['flag']} {j['lo']}-{j['hi']}")

print("\n[5] 样例报告回归：结果不能变")
parsed, skipped = [], []
for line in SAMPLE_REPORT.splitlines():
    s = line.strip()
    if not s or set(s) <= set("-- "):
        continue
    e = parse_line(s, LOOKUP)
    if e:
        parsed.append((e, judge(e, SAMPLE_REPORT)))
check("仍识别 14 项", len(parsed) == 14, str(len(parsed)))
ab = [(e, j) for e, j in parsed if j["flag"] != "正常"]
check("仍 8 项异常", len(ab) == 8, str(len(ab)))
check("样例里没有误报危急值", all(j["critical"] is None for _, j in parsed))
check("样例里没有误换算", all(not j["converted"] for _, j in parsed))

print("\n[6] 边界：没有年龄/性别时不能崩")
for line in ["K 血清钾 6.8 mmol/L 3.5-5.3", "HGB 血红蛋白 120 g/L"]:
    e, j = one(line, "")
    check(f"无人口信息也能判: {line.split()[0]}", j["flag"] in ("偏高", "偏低", "正常"))
check("危急值在无性别时仍能匹配成人条目",
      one("K 血清钾 2.2 mmol/L", "")[1]["critical"] == "危急低值 2.5")

print("\n[7] pick_population 直接调用")
hgb = next(x for x in [parse_line("HGB 血红蛋白 1 g/L", LOOKUP)["item"]] if x["name"] == "血红蛋白")
check("男性 → 成年男性条目", pick_population(hgb["reference_ranges"], "性别：男 年龄：40")["population"] == "成年男性")
check("女性 → 成年女性条目", pick_population(hgb["reference_ranges"], "性别：女 年龄：40")["population"] == "成年女性")
check("未给性别 → 退回首个", pick_population(hgb["reference_ranges"], "")["population"] == "成年男性")

print("\n[8] 临床决定水平（decision_levels）")
e, j = one("HGB 血红蛋白 40 g/L 130-175", "性别：男 年龄：35")
lv = [d["level"] for d in j["decisions"]]
check("HGB 40 触发两档, 最严重在前", lv == [45, 70], str(lv))
check("带临床动作", "输注红细胞" in j["decisions"][0]["action"], j["decisions"][0]["action"][:20])

e, j = one("HGB 血红蛋白 60 g/L 130-175", "性别：男 年龄：35")
check("HGB 60 只触发 70 那档", [d["level"] for d in j["decisions"]] == [70],
      str([d["level"] for d in j["decisions"]]))

e, j = one("K 血清钾 7.2 mmol/L 3.5-5.3", "性别：男 年龄：35")
lv = [d["level"] for d in j["decisions"]]
check("血钾 7.2 三档全触发且降序", lv == [7.0, 6.0, 5.5], str(lv))
check("最高档带急救动作", "透析" in j["decisions"][0]["action"], j["decisions"][0]["action"][:24])

e, j = one("K 血清钾 3.1 mmol/L 3.5-5.3", "性别：男 年龄：35")
check("血钾 3.1 未达任何决定水平", j["decisions"] == [], str(j["decisions"]))

e, j = one("HGB 血红蛋白 140 g/L 130-175", "性别：男 年龄：35")
check("正常项不显示决定水平", j["decisions"] == [] and j["interference"] == [])

print("\n[9] 干扰因素（interference_factors）")
e, j = one("K 血清钾 6.8 mmol/L 3.5-5.3", "性别：男 年龄：35")
names = [f["factor"] for f in j["interference"]]
check("偏高时挑 elevated 方向", any("溶血" in n for n in names), str(names)[:60])
check("带机制和识别方法", all(f["mechanism"] and f["detect"] for f in j["interference"]))
check("最多 3 条", len(j["interference"]) <= 3, str(len(j["interference"])))

e, j = one("HGB 血红蛋白 100 g/L 130-175", "性别：男 年龄：35")
names = [f["factor"] for f in j["interference"]]
check("偏低时挑 decreased 方向", any("输液同侧采血" in n for n in names), str(names)[:60])

print("\n[10] 解读 prompt 是否带上这两块")
from report_rag import build_prompt

e, j = one("K 血清钾 7.2 mmol/L 3.5-5.3", "性别：男 年龄：35")
p = build_prompt(e, j)
check("prompt 含临床决定水平区块", "【临床决定水平 · 已达到】" in p and "- 7 严重高钾" in p,
      p[p.find("【临床决定水平 · 已达到】"):][:42])
check("prompt 含干扰因素区块", "【干扰因素 · 可能造成假性结果】" in p and "标本溶血" in p)

e, j = one("HGB 血红蛋白 140 g/L 130-175", "性别：男 年龄：35")
p = build_prompt(e, j)
check("正常项 prompt 不带这两个区块",
      "【临床决定水平 · 已达到】" not in p and "【干扰因素 · 可能造成假性结果】" not in p)

print("\n[11] 追问上下文（material_block）也带上")
import app
e, j = one("K 血清钾 7.2 mmol/L 3.5-5.3", "性别：男 年龄：35")
blk = app.material_block(e, j)
check("上下文含决定水平", "临床决定水平" in blk and "7" in blk)
check("上下文含假性干扰", "假性干扰" in blk)

print("\n" + ("全部通过 ✅" if ok else "有失败项 ❌"))
sys.exit(0 if ok else 1)
