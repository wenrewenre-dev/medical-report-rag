# scripts/query_rewrite.py —— 查询改写 / HyDE：检索之前先把问题变成"检索友好"的样子
#
# 两种手段（可单用可叠加）：
#   rewrite —— 让 LLM 把口语问题改写成 2-3 条检索查询，覆盖项目全名/缩写/俗称
#              例："没力气是不是贫血" → "血红蛋白 参考范围 降低意义"、"HGB 偏低 临床意义"
#   hyde    —— Hypothetical Document Embeddings：先让 LLM 写一段假设性的知识库条目，
#              再拿这段内容去检索。短问句缺的是上下文，假设性答案正好补上
#
# 策略：off / rewrite / hyde / both（实测结论见 README：hybrid 检索路径上 rewrite 最优，
#       HyDE 的收益出现在纯语义路径，两者叠加会互相稀释）
# 约定：任何失败都退回原问题，检索不能因为改写挂了就不可用
import os
import re

REWRITE_SYSTEM = """你是医学检验知识库的检索助手。用户会以口语化的方式提问，你要把问题改写成 3 条更适合检索的查询。

规则：
1. 每条查询都要落到具体检验指标上，优先用项目全名（如"血红蛋白""丙氨酸氨基转移酶"），可辅以常用缩写（HGB、ALT）。
2. 三条查询分别覆盖：项目全名 + 参考范围/临床意义、英文缩写、以及同义或俗称说法。
3. 如果问题只描述了症状（如"没力气""头晕"），就改写成该症状最常对应的检验指标。
4. 只输出查询本身：每行一条，不要编号、不要引号、不要解释、不要加"查询："之类的前缀。
"""

HYDE_SYSTEM = """你是检验知识库条目的写作者。用户会提出一个口语化的问题，你要写出一段"知识库条目会怎么回答它"的假设性内容。

规则：
1. 只写检验指标的通用知识：参考区间、升高/降低的临床意义、常见相关疾病、复查建议。
2. 不要编造具体患者的检验数值，不要下诊断，不要推荐药物。
3. 2-4 句话，直接写条目内容；不要复述任务，不要解释你在假设什么。
"""

# 去掉 "1." "1、" "1)" "- " "• " 这类编号/项目符号
_BULLET = re.compile(r"^\s*(?:[-*•·]|[（(]?\d+\s*[.、)）])\s*")
MAX_VARIANTS = 3


def make_client():
    """给 CLI/评测脚本用；Web 界面直接用 app.py 里那个 client"""
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv()
    return OpenAI(api_key=os.getenv("LLM_API_KEY"), base_url=os.getenv("LLM_BASE_URL"))


def _chat(client, system: str, user: str, max_tokens: int, temperature: float = 0.3) -> str:
    """固定指令在 system、变化内容在 user —— 与其他管线一致的缓存友好摆位"""
    resp = client.chat.completions.create(
        model=os.getenv("LLM_MODEL"),
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
    )
    return (resp.choices[0].message.content or "").strip()


def _parse_variants(text: str, limit: int = MAX_VARIANTS):
    """把 LLM 输出解析成查询列表：去编号、去引号、去重、限条数"""
    out = []
    for raw in text.splitlines():
        s = _BULLET.sub("", raw).strip().strip("「」\"'“”")
        if len(s) < 2 or s in out:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def rewrite_variants(question: str, client, limit: int = MAX_VARIANTS):
    """口语问题 → 2-3 条检索查询（不含原问题）"""
    text = _chat(client, REWRITE_SYSTEM, question, max_tokens=200)
    return _parse_variants(text, limit)


def hyde_document(question: str, client) -> str:
    """口语问题 → 一段假设性的知识库条目（HyDE 的"假设文档"）"""
    doc = _chat(client, HYDE_SYSTEM, question, max_tokens=300)
    return " ".join(doc.split())        # 压成一行，避免换行干扰分词


def build_queries(question: str, client, strategy: str = "both"):
    """strategy: off | rewrite | hyde | both → 返回 [原问题, ...改写]"""
    question = (question or "").strip()
    if not question or strategy == "off" or client is None:
        return [question] if question else []

    queries = [question]
    try:
        if strategy in ("rewrite", "both"):
            queries += rewrite_variants(question, client)
        if strategy in ("hyde", "both"):
            doc = hyde_document(question, client)
            if doc:
                queries.append(doc)
    except Exception as e:                 # 断网/额度/超时：宁可只用原问题，也不能让检索挂掉
        print(f"    [改写] 失败, 退回原问题: {type(e).__name__}: {e}")

    uniq = []
    for q in queries:
        if q and q not in uniq:
            uniq.append(q)
    return uniq
