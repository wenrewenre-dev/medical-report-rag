# scripts/test_anonymize.py —— 报告脱敏的回归测试
# 跑法：python scripts/test_anonymize.py
# 重点验三件事：该抹的抹掉了、不该动的（指标行/性别）一格没动、送进 LLM 的 prompt 里没有 PHI
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anonymize as an
from parse_report import load_lookup, parse_line, judge, SAMPLE_REPORT

PHI = ["张三", "110101199001011234", "13800138000", "MR20240001",
       "S240501001", "北京市朝阳区某某路1号", "zhang@example.com", "2024-05-01"]

HEADER = """检验报告单
姓名：张三  性别：男  年龄：35
身份证号：110101199001011234
手机号：13800138000
病历号：MR20240001
样本号：S240501001
住址：北京市朝阳区某某路1号
邮箱：zhang@example.com
采样时间：2024-05-01
标本：静脉血
--------------------------------------
"""
REPORT = HEADER + SAMPLE_REPORT

ok = True


def check(name, cond, detail=""):
    global ok
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  {detail}" if detail else ""))
    ok = ok and cond


print("\n[1] 抹掉 PHI，保留标签与性别")
clean, counts = an.anonymize_with_report(REPORT)
print("   命中:", counts)
for p in PHI:
    check(f"已抹掉 {p[:6]}…", p not in clean)
check("标签保留", "姓名：[已脱敏]" in clean and "病历号：[已脱敏]" in clean)
check("性别保留（参考区间要用）", "性别：男" in clean)
check("年龄保留", "年龄：35" in clean)

print("\n[2] 指标行一格都不能动")
for line in SAMPLE_REPORT.splitlines():
    s = line.strip()
    if not s or s.startswith(("检验报告单", "姓名", "标本", "---")):
        continue
    check(f"未改动: {s[:24]}", s in clean)

print("\n[2b] 年龄可选：keep_age=False 时一并抹掉")
check("默认保留年龄", "年龄：35" in clean)
masked_age = an.anonymize(REPORT, keep_age=False)
check("关掉后年龄被抹", "年龄：[已脱敏]" in masked_age and "年龄：35" not in masked_age)
check("性别仍然保留", "性别：男" in masked_age)

print("\n[3] 幂等 + 空输入 + 无 PHI 原样返回")
check("再跑一次不变", an.anonymize(clean) == clean)
check("空文本", an.anonymize("") == "")
plain = "HGB  血红蛋白  112  g/L  130-175"
check("无 PHI 时原样返回", an.anonymize(plain) == plain)

print("\n[4] OCR 连写/裸号码")
check("无空格连写", "张三" not in an.anonymize("姓名：张三性别：男年龄：35"))
bare = an.anonymize("患者 110101199001011234 电话 13800138000 于 2024/05/01 采样")
check("裸身份证/手机/日期都被抹", all(x not in bare for x in ("110101199001011234", "13800138000", "2024/05/01")))

print("\n[5] 脱敏后解析与判定不受影响")
_, lookup = load_lookup()
parsed = [(e, judge(e, clean)) for e in (parse_line(l.strip(), lookup) for l in clean.splitlines()) if e]
check("仍解析出 14 项", len(parsed) == 14, str(len(parsed)))
hgb = next((e, j) for e, j in parsed if e["item"]["name"] == "血红蛋白")
check("仍按男性区间判定", (hgb[1]["lo"], hgb[1]["hi"]) == (130, 175) and hgb[1]["flag"] == "偏低")

print("\n[6] 管线泄漏检查：送进 LLM 的每条消息都不含 PHI")
try:
    import app
except Exception as e:                     # 没装 OCR/检索依赖时跳过，别让隐私测试挡住别的活
    print(f"   跳过（import app 失败: {type(e).__name__}）")
    sys.exit(0 if ok else 1)

import json
import tempfile

# 审计写到临时文件，别污染真实日志
an.AUDIT_PATH = os.path.join(tempfile.mkdtemp(), "audit.jsonl")

calls = []
app.complete = lambda messages: (calls.append(messages) or "假解读")
app.complete_stream = lambda messages: (calls.append(messages) or iter(["假追问回答"]))

frames = list(app.report_fn(REPORT))
check("状态栏公示脱敏", "已脱敏" in frames[0][1])
check("表格/解读无 PHI", all(p not in frames[-1][0] + frames[-1][1] for p in PHI))
check("追问上下文无 PHI", all(p not in frames[0][3] for p in PHI))
check("确实调过模型", len(calls) > 0)
leaks = [p for msgs in calls for m in msgs for p in PHI if p in m["content"]]
check("prompt 零泄漏", not leaks, str(leaks))

list(app.report_chat_fn("第2项异常怎么办?", [], frames[0][3]))
leaks = [p for msgs in calls[-1:] for m in msgs for p in PHI if p in m["content"]]
check("追问 prompt 零泄漏", not leaks, str(leaks))

print("\n[7] 审计落盘：只记类别和处数，不记原值")
records = [json.loads(l) for l in open(an.AUDIT_PATH, encoding="utf-8") if l.strip()]
check("有审计记录", len(records) >= 1, f"{len(records)} 条")
rec = records[-1]
check("记录类型/计数", rec["kind"] == "report" and rec["total"] > 0 and "姓名" in rec["counts"], str(rec))
raw = open(an.AUDIT_PATH, encoding="utf-8").read()
check("审计里没有任何 PHI 原值", all(p not in raw for p in PHI))

print("\n[8] 问答输入也脱敏：展示原文，送模型的是脱敏版")
calls.clear()
qa_q = "帮我看看这份报告：姓名：王五 手机 13900139000 HGB 108 g/L 115-150 偏低吗"
frames = list(app.qa_fn(qa_q, [], False))
check("界面历史保留原文", "王五" in frames[-1][1][0]["content"])
leaks = [p for msgs in calls for m in msgs for p in ("王五", "13900139000") if p in m["content"]]
check("问答 prompt 零泄漏", not leaks, str(leaks))
src = next((f[2] for f in frames if isinstance(f[2], str) and "问题已脱敏" in str(f[2])), "")
check("资料面板提示已脱敏", bool(src), src.splitlines()[-1][:40] if src else "(无)")
records = [json.loads(l) for l in open(an.AUDIT_PATH, encoding="utf-8") if l.strip()]
check("问答审计也落了一条", records[-1]["kind"] == "question" and "电话" in records[-1]["counts"],
      str(records[-1]["counts"]))

print("\n" + ("全部通过 ✅" if ok else "有失败项 ❌"))
sys.exit(0 if ok else 1)
