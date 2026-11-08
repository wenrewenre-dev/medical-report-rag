# scripts/app.py — 第7步: Web界面
# 原则: 界面层不写AI逻辑, 全部复用前几步的模块
# 缓存约定: 固定指令在前、变化内容在后（与 report_rag.py 的 build_prompt/build_summary_prompt 一致, README §9.4）
import os
# ⚠️ 必须在 import gradio 之前: HF_ENDPOINT 在库被 import 的瞬间就被读取定格
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_OFFLINE"] = "0"   # 模型已完整缓存: 跳过一切联网校验, 启动更快
import re
import gradio as gr
from dotenv import load_dotenv
from openai import OpenAI

from kb import KB
from parse_report import load_lookup, parse_line, judge, SAMPLE_REPORT, NUM
from report_rag import build_prompt, build_summary_prompt, SYSTEM_PROMPT, DISCLAIMER  # 直接复用, 一行不重写

load_dotenv()

print("初始化: 加载检索模块（首次约10-30秒, 请稍候）...")
kb = KB()
_, lookup = load_lookup()
client = OpenAI(api_key=os.getenv("LLM_API_KEY"), base_url=os.getenv("LLM_BASE_URL"))


def chat(user_prompt: str) -> str:
    resp = client.chat.completions.create(
        model=os.getenv("LLM_MODEL"),
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    # 缓存监控: 同一管线的调用中, 命中应从第2-3次起爬坡（前1-2次miss=落盘, 属正常）
    u = resp.usage
    extra = u.model_extra or {}
    hit = getattr(u, "prompt_cache_hit_tokens", 0) or extra.get("prompt_cache_hit_tokens", 0)
    print(f"    [缓存] 命中{hit} / 总输入{u.prompt_tokens}")
    return resp.choices[0].message.content


# ---------- 页签1: 自由问答 (第4步的RAG路径) ----------
def qa_fn(question: str):
    if not question.strip():
        return "请先输入问题。", ""
    results = kb.search(question, k=3)
    ctx = "\n\n".join(f"[资料{r['id']}] {r['name']}\n{r['text']}" for r in results)
    # 缓存友好摆位: 固定指令在前, 变化内容（资料+问题）在后
    prompt = (f"【回答要求】请依据下面的资料回答, 句末引用[资料X]; 资料覆盖不到的部分请明确说明。\n\n"
              f"【知识库资料】\n{ctx}\n\n"
              f"【用户问题】{question}")
    answer = chat(prompt) + DISCLAIMER
    src = "\n\n".join(f"**资料{r['id']}** | {r['name']}" for r in results)
    return answer, f"### 🔍 检索命中的资料\n\n{src}"


# ---------- 页签2: 报告解读 (第5步的路径) ----------
def parse_table(parsed, skipped):
    rows = ["| 项目 | 结果 | 参考范围 | 判定 |", "|---|---|---|---|"]
    for e, j in parsed:
        it = e["item"]
        rows.append(f"| {it['name']} | {e['value']} {it['unit']} | "
                    f"{j['lo']}-{j['hi']} | {j['flag']}{j['arrow']} |")
    md = "\n".join(rows)
    if skipped:
        md += "\n\n> ⚠️ 知识库未收录, 未做解读: " + "、".join(skipped)
    return md


def report_fn(report_text: str):
    """生成器函数: 每完成一步就 yield 一次, 界面即时刷新"""
    if not report_text.strip():
        yield "请先粘贴报告内容。", ""
        return

    # ① 解析
    parsed, skipped = [], []
    for line in report_text.splitlines():
        line = line.strip()
        if not line or set(line) <= set("-- "):
            continue
        entry = parse_line(line, lookup)
        if entry:
            parsed.append((entry, judge(entry, report_text)))
        elif re.search(rf"{NUM}\s*[-~～]\s*{NUM}", line):
            skipped.append(line)

    if not parsed:
        yield "未能识别任何指标。请检查格式: 每行应为「缩写 名称 数值 单位 范围」。", ""
        return

    abnormals = [(e, j) for e, j in parsed if j["flag"] != "正常"]
    table_md = parse_table(parsed, skipped)
    yield table_md, f"✅ 识别 {len(parsed)} 项, 异常 {len(abnormals)} 项, 开始逐项解读..."

    # ② 逐项解读 (流式追加)——build_prompt 已是"固定指令在前"的缓存友好结构
    all_md = ""
    for i, (e, j) in enumerate(abnormals, 1):
        it = e["item"]
        all_md += (f"\n\n---\n\n### 📌 异常{i}: {it['name']} "
                   f"{e['value']}{it['unit']}({j['flag']}{j['arrow']})\n\n")
        all_md += chat(build_prompt(e, j)) + DISCLAIMER
        yield table_md, all_md.strip()

    # ③ 综合总结 (资料必须随行——LLM每次调用都是无状态的)
    # 总结 prompt 复用 report_rag.build_summary_prompt, 消灭双份手抄
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
        summary_prompt = build_summary_prompt(materials)
        all_md += "\n\n---\n\n# 📋 报告综合总结\n\n" + chat(summary_prompt) + DISCLAIMER
        yield table_md, all_md.strip()


with gr.Blocks(title="检验报告智能解读") as demo:
    gr.Markdown("# 🏥 检验报告智能解读系统\n基于本地知识库的RAG问答与报告解析|AI生成, 仅供参考")
    with gr.Tab("💬 指标问答"):
        q = gr.Textbox(label="你的问题", placeholder="例如: 最近总觉得没力气, 是不是贫血?")
        btn1 = gr.Button("提问", variant="primary")
        ans = gr.Markdown()
        src = gr.Markdown()
        btn1.click(qa_fn, inputs=q, outputs=[ans, src])
    with gr.Tab("📋 报告解读"):
        rep = gr.Textbox(label="粘贴报告文本", value=SAMPLE_REPORT, lines=14)
        btn2 = gr.Button("解析并解读", variant="primary")
        table = gr.Markdown()
        interp = gr.Markdown()
        btn2.click(report_fn, inputs=rep, outputs=[table, interp])

if __name__ == "__main__":
    demo.launch(inbrowser=True)

