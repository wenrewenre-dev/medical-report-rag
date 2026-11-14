# scripts/judge.py —— LLM-as-a-Judge：让模型给回答打分
#
# 三项审核（对应 README 里"不编造、必引用"的承诺）：
#   ① 引用真实性：回答里的 [资料X] 是否都真在检索资料里（这一项另用正则做机器复核）
#   ② 结论支持度：回答的结论能否在资料里找到依据
#   ③ 数字编造：回答里的检验数值/参考范围/百分比是否都有出处
#
# 输出统一成 dict，方便评测脚本汇总；JSON 解析失败不抛异常，返回 error 字段由调用方处理。
import json
import os
import re

JUDGE_SYSTEM = """你是检验报告问答的质量审核员。给定【用户问题】【检索资料】【助手回答】，你按三项审核这份回答。

审核标准：
1. 引用真实性：回答里每个 [资料X] 必须在【检索资料】里出现过；引用了不存在的编号即不合格。
2. 结论支持度：回答的结论必须能在【检索资料】里找到依据；出现资料里没有的说法即不合格。
3. 数字编造：回答里的检验数值、参考范围、百分比，必须能追溯到【检索资料】或【用户问题】；凭空出现的数字即不合格。

只输出一个 JSON 对象，不要代码块、不要额外解释：
{"citation_valid": true 或 false,
 "bad_citations": ["资料99"],
 "supported": "yes" 或 "partial" 或 "no",
 "unsupported_claims": ["资料里没有的结论"],
 "fabricated_numbers": ["120-130 g/L"],
 "pass": true 或 false,
 "reason": "不超过40字的判词"}

判定口径：三项都合格才 pass=true；supported=partial 时看偏离程度，关键结论错误必须 pass=false。"""

CITATION_RE = re.compile(r"\[资料(\d+)\]")


def citations(answer: str):
    """回答里引用到的资料编号（去重、保序）"""
    seen = []
    for num in CITATION_RE.findall(answer or ""):
        if num not in seen:
            seen.append(num)
    return seen


def sources_block(sources) -> str:
    """kb.search 的结果 → 给裁判看的资料文本"""
    blocks = []
    for s in sources:
        blocks.append(f"[资料{s['id']}] {s['name']}\n{s['text']}")
    return "\n\n".join(blocks)


def _parse_json(text: str):
    """裁判偶尔会裹代码块或加解释，这里尽量把 JSON 抠出来"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


_BOOL_FIELDS = {"pass": r'"?pass"?\s*:\s*(true|false)',
                "citation_valid": r'"?citation_valid"?\s*:\s*(true|false)'}
_STR_FIELDS = {"supported": r'"?supported"?\s*:\s*"?(yes|partial|no)'}


def _parse_fields(text: str):
    """整段 JSON 解析失败时的兜底：单字段抠。裁判偶尔会漏引号、多解释，别因此丢整轮结果"""
    data = {}
    for key, pat in _BOOL_FIELDS.items():
        m = re.search(pat, text or "", re.I)
        if m:
            data[key] = m.group(1).lower() == "true"
    for key, pat in _STR_FIELDS.items():
        m = re.search(pat, text or "", re.I)
        if m:
            data[key] = m.group(1).lower()
    return data or None


def _ask(client, model, system, user):
    """返回（内容, finish_reason）。
    ⚠️ max_tokens 必须留足：推理型模型的思维链 token 也计入这个预算，
    卡太紧会出现"reasoning 吃光预算、正文为空"的假失败（实测 600 时偶发）"""
    resp = client.chat.completions.create(
        model=model or os.getenv("LLM_MODEL"),
        temperature=0,                       # 裁判要稳定，不要发挥
        max_tokens=1500,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
    )
    choice = resp.choices[0]
    return choice.message.content or "", choice.finish_reason


def judge_answer(question: str, answer: str, sources, client, model: str = None) -> dict:
    """返回裁判结论 dict。sources 是 kb.search 的结果列表（含 id/name/text）。"""
    source_ids = [str(s["id"]) for s in sources]
    user = (f"【用户问题】\n{question}\n\n"
            f"【检索资料】\n{sources_block(sources)}\n\n"
            f"【助手回答】\n{answer}")

    data, raw, degraded, finish = None, "", False, None
    for attempt in range(3):                  # 偶发空响应/畸形输出，重试几次；仍不行就报 error
        raw, finish = _ask(client, model, JUDGE_SYSTEM, user)
        data = _parse_json(raw)
        if data is not None:
            break
        data = _parse_fields(raw)             # 兜底：能抠出 pass/citation_valid 也算数
        if data is not None:
            degraded = True
            break

    # 机器复核引用：裁判说有/没有，都要和正则结果对得上（对不上说明裁判漏看）
    cited = citations(answer)
    bad_rule = [c for c in cited if c not in source_ids]

    if data is None:
        why = "输出为空且被截断" if finish == "length" else "裁判输出不是合法 JSON"
        return {"pass": None, "error": why, "raw": raw[:200], "finish": finish,
                "cited": cited, "bad_citations_rule": bad_rule}

    def _as_list(key):
        v = data.get(key) or []
        return [str(x) for x in v] if isinstance(v, list) else [str(v)]

    judge_bad = _as_list("bad_citations")
    return {
        "pass": bool(data.get("pass")),
        "citation_valid": bool(data.get("citation_valid")),
        "bad_citations": judge_bad,
        "supported": str(data.get("supported", "")).lower(),
        "unsupported_claims": _as_list("unsupported_claims"),
        "fabricated_numbers": _as_list("fabricated_numbers"),
        "reason": str(data.get("reason", ""))[:80],
        "degraded": degraded,
        # 机器侧证据，用来验裁判有没有看漏
        "cited": cited,
        "bad_citations_rule": bad_rule,
        "citation_agree": (not judge_bad) == (not bad_rule),
    }
