# scripts/report_rag.py — 第5步下半场：解析结果 → 逐项LLM解读 → 全报告总结
# 检索策略：解析已精确匹配知识库条目，无需向量检索（能精确匹配就别绕道语义检索）
# 缓存约定：固定模板在前、变化内容在后（DeepSeek 前缀缓存只认第0个token起的公共前缀，README §9.4）
import os
import re
from dotenv import load_dotenv
from openai import OpenAI

from parse_report import load_lookup, parse_line, judge, SAMPLE_REPORT, NUM

load_dotenv()

SYSTEM_PROMPT = """你是检验报告解读助手，正在为用户逐项解读化验报告中发现异常指标。

回答规则：
1. 只依据【知识库资料】中的内容解读，禁止编造资料里没有的医学事实。
2. 引用格式：句末标注 [资料X]。
3. 不下诊断、不推荐具体药物；涉及治疗决策一律建议咨询医生。
4. 用通俗中文，术语首次出现用括号解释；语气平和，不制造恐慌。
5. 如果结果达到危急值，第一句就要明确提醒尽快就医。
"""

# 行为指令抽成模块级常量：逐字节固定，才能进公共前缀吃缓存价
GUIDE = """请解读这个结果，包含三部分：
1. **结论**: 偏离正常多少、说明什么、紧急程度如何
2. **可能原因**: 依据资料列2-3个最可能的
3. **下一步建议**: 依据资料的复检建议—查什么、什么时候查、看什么科"""

SUMMARY_GUIDE = """请基于以上资料生成报告综合总结，包含：
1. **整体情况**: 2-3句话概括这些异常共同提示什么方向
2. **优先级排序**: 哪个最需要优先处理，为什么（危急值 > 显著异常 > 轻度异常）
3. **下一步行动清单**: 复查哪些项目、间隔多久、挂什么科
规则同上：只依据【知识库资料】、引用[资料X]、不下诊断。"""

DISCLAIMER = "\n\n---\n🔧 免责声明：AI生成，仅供参考，不能替代专业医疗建议。"

def build_prompt(entry, j) -> str:
    """把'结构化事实 + 该项知识库资料'组装成解读任务。
    摆位约定：固定指令在前、变化内容在后——公共前缀 = SYSTEM_PROMPT + GUIDE"""
    it = entry["item"]
    ranges = "；".join(
        f"{r['population']} {r['low']}-{r['high']}" for r in it["reference_ranges"]
    )
    critical_line = f"⚠️ 该值已达到{j['critical']}，属危急值! " if j["critical"] else ""
    return f"""【解读要求】
{GUIDE}

【本次结果】{it['name']}({'/'.join(it['abbr'])}) = {entry['value']} {it['unit']}
参考范围 {j['lo']}-{j['hi']} (来源{j['src']}) → 判定：{j['flag']} {j['arrow']}
{critical_line}
【知识库资料 · 资料{it['id']}】
参考区间：{ranges}
升高意义：{it['elevated_meaning']}
降低意义：{it['decreased_meaning']}
相关疾病：{'、'.join(it['related_diseases'])}
复检建议：{it['recheck_advice']}
注意事项：{it.get('notes', '无')}"""

def build_summary_prompt(materials: str) -> str:
    """综合总结 prompt（固定指令在前、资料在后）。app.py 也复用这份，消除双份手抄。"""
    return f"""【解读要求】
{SUMMARY_GUIDE}

【知识库资料】
{materials}"""

def chat(client, user_prompt: str) -> str:
    resp = client.chat.completions.create(
        model=os.getenv("LLM_MODEL"),
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    # 缓存监控：同一管线的调用中，命中数应从第2-3次起爬坡（前1-2次miss=落盘，属正常）
    u = resp.usage
    extra = u.model_extra or {}
    hit = getattr(u, "prompt_cache_hit_tokens", 0) or extra.get("prompt_cache_hit_tokens", 0)
    print(f"    [缓存] 命中{hit} / 总输入{u.prompt_tokens}")
    return resp.choices[0].message.content

def main():
    _, lookup = load_lookup()
    report = SAMPLE_REPORT
    client = OpenAI(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
    )

    # ① 解析（复用上半场的函数）
    parsed, skipped = [], []
    for line in report.splitlines():
        line = line.strip()
        if not line or set(line) <= set("-- "):
            continue
        entry = parse_line(line, lookup)
        if entry:
            parsed.append((entry, judge(entry, report)))
        elif re.search(rf"{NUM}\s*[-~～]\s*{NUM}", line):
            skipped.append(line)

    abnormals = [(e, j) for e, j in parsed if j["flag"] != "正常"]
    print(f"📋 解析完成: 识别{len(parsed)}项 | 异常{len(abnormals)}项 | 未收录{len(skipped)}项")
    for s in skipped:
        print(f"  ❓ 未收录，不做解读: {s.split()[1] if len(s.split())>1 else s}")

    # ② 逐项解读异常项
    for i, (e, j) in enumerate(abnormals, 1):
        it = e["item"]
        print(f"\n{'='*55}\n📌 异常{i}: {it['name']} {e['value']}{it['unit']}({j['flag']}{j['arrow']})\n")
        print(chat(client, build_prompt(e, j)) + DISCLAIMER)

    # ③ 全报告综合总结（跨项归纳）
    # 关键修复：总结调用也必须附上知识库资料——
    # LLM每次调用都是无状态的，之前逐项解读给过的资料它"不记得"
    if abnormals:
        blocks = []
        for e, j in abnormals:
            it = e["item"]
            blocks.append(
                f"[资料{it['id']}] {it['name']}({'/'.join(it['abbr'])})\n"
                f"本次结果: {e['value']} {it['unit']}"
                f"({j['flag']}{j['arrow']}, 参考范围{j['lo']}-{j['hi']}, 来源{j['src']})\n"
                f"升高意义: {it['elevated_meaning']}\n"
                f"降低意义: {it['decreased_meaning']}\n"
                f"相关疾病: {'、'.join(it['related_diseases'])}\n"
                f"复检建议: {it['recheck_advice']}"
            )
        materials = "\n\n".join(blocks)

        print(f"\n{'#'*55}\n📋 报告综合总结\n{'#'*55}")
        print(chat(client, build_summary_prompt(materials)) + DISCLAIMER)

if __name__ == "__main__":
    main()

