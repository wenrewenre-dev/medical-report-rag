# scripts/app.py — 第7步: Web界面 / 第8步: 多轮对话
# 原则: 界面层不写AI逻辑, 全部复用前几步的模块
# 缓存约定: 固定指令在前、变化内容在后（与 report_rag.py 的 build_prompt/build_summary_prompt 一致, README §9.4）
#
# 多轮对话（第8步）四个约定:
#   1. 历史用 gr.Chatbot(type="messages") 的 [{"role","content"}] 结构: 界面显示与送进LLM的是同一份数据
#   2. 追问检索: 问题里认不出知识库主体词时, 用"话题锚点"（最近一条认得出主体词的提问）融合检索
#   3. 历史窗口: 最近 MAX_TURNS 轮 + 字符预算兜底, 防止prompt无限增长
#   4. 缓存: system段逐字节固定, 是唯一能跨轮复用的公共前缀; 其后的历史每轮都变, 属预期
import os
# ⚠️ 必须在 import gradio 之前: HF_ENDPOINT 在库被 import 的瞬间就被读取定格
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_OFFLINE"] = "0"   # 模型已完整缓存: 跳过一切联网校验, 启动更快
import re
import gradio as gr
from dotenv import load_dotenv
from openai import OpenAI

from kb import KB
from parse_report import load_lookup, parse_line, judge, find_item, SAMPLE_REPORT, NUM
from report_rag import build_prompt, build_summary_prompt, SYSTEM_PROMPT, DISCLAIMER  # 直接复用, 一行不重写

load_dotenv()

print("初始化: 加载检索模块（首次约10-30秒, 请稍候）...")
kb = KB()
_, lookup = load_lookup()
client = OpenAI(api_key=os.getenv("LLM_API_KEY"), base_url=os.getenv("LLM_BASE_URL"))

# ---------- 多轮对话配置 ----------
MAX_TURNS = 6                 # prompt里最多带最近6轮（6问6答）, 更早的丢弃
MAX_HISTORY_CHARS = 6000      # 字符预算兜底: 单条回答很长时, 少带几轮

# 问答专用system: 逐字节固定。同一会话里它永远是第0条, 前缀缓存才有公共前缀可认
QA_SYSTEM = SYSTEM_PROMPT + """补充规则（多轮问答）：
6. 用户可能顺着你上一轮的回答追问, 请结合对话历史理解"这个""那"等指代。
7. 引用编号只认本轮【知识库资料】; 历史轮次里的编号不再有效。
8. 免责声明由界面统一展示, 回答里不必重复输出。
"""

# 报告追问专用system: 固定规则在前, 本次报告内容在后（报告一变只有后半段变）
REPORT_CHAT_SYSTEM = SYSTEM_PROMPT + """补充规则（就本次报告追问）：
6. 用户会针对上面这份报告连续追问, 请结合【本次报告指标】和【指标知识库资料】回答。
7. 引用只认【指标知识库资料】里的编号, 句末标注 [资料X]。
8. 只依据本次报告和资料回答; 报告里没有的指标、资料里没有的说法, 明确说明未覆盖, 不要编造。
9. 免责声明由界面统一展示, 回答里不必重复输出。
"""


def complete(messages: list) -> str:
    """统一LLM调用口: 收完整messages数组, 多轮历史由调用方拼好"""
    resp = client.chat.completions.create(
        model=os.getenv("LLM_MODEL"),
        temperature=0.2,
        messages=messages,
    )
    # 缓存监控: 同一管线的调用中, 命中应从第2-3次起爬坡（前1-2次miss=落盘, 属正常）
    u = resp.usage
    extra = u.model_extra or {}
    hit = getattr(u, "prompt_cache_hit_tokens", 0) or extra.get("prompt_cache_hit_tokens", 0)
    print(f"    [缓存] 命中{hit} / 总输入{u.prompt_tokens}")
    return resp.choices[0].message.content


def chat(user_prompt: str) -> str:
    """单轮调用: 报告解读管线沿用（那里的资料本来就随行, 不需要历史）"""
    return complete([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])


# ---------- 页签1: 自由问答（多轮）----------
def trim_history(history: list) -> list:
    """历史裁剪: 先按轮数, 再按字符预算; 只从轮次边界切, 保证user/assistant成对出现"""
    msgs = [m for m in history
            if isinstance(m, dict) and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str) and m["content"].strip()]
    msgs = msgs[-MAX_TURNS * 2:]
    while msgs and msgs[0]["role"] != "user":      # 不能以assistant开头, 否则assistant失去发问对象
        msgs.pop(0)
    total = sum(len(m["content"]) for m in msgs)
    while msgs and total > MAX_HISTORY_CHARS:
        total -= len(msgs.pop(0)["content"])       # 丢一整轮: 先丢问题
        while msgs and msgs[0]["role"] != "user":  # 再丢它对应的回答
            total -= len(msgs.pop(0)["content"])
    return msgs


def has_subject(text: str) -> bool:
    """问题里是否出现了知识库认得的主体词（项目名/缩写/别名）"""
    return find_item(text, lookup) is not None


def find_anchor(history: list) -> str:
    """话题锚点: 最近一条认得出主体词的提问。
    连问"那需要复查什么?→那饮食要注意什么?"时, 上一问本身也是追问,
    拿它融合会把话题带丢; 往上找到真正带主体的那一问, 追问才不会跑偏。
    整段对话都没主体词时（常见: 从症状"总觉得没力气"问起）退回第一条提问, 它就是这段对话的主题。"""
    first = ""
    for m in history:
        if m.get("role") == "user" and isinstance(m.get("content"), str) and m["content"].strip():
            first = m["content"]
            break
    for m in reversed(history):
        if (m.get("role") == "user" and isinstance(m.get("content"), str)
                and has_subject(m["content"])):
            return m["content"]
    return first


def retrieve(question: str, anchor: str, k: int = 3):
    """追问检索: 本轮问题认不出主体词时, 把话题锚点拼进检索query。
    "那需要复查什么?"/"能吃什么?" 单独检索只会召回无关条目;
    而问题自带主体词（"血糖多少算高?"）时只按本轮检索, 避免被旧话题带偏。"""
    if anchor and not has_subject(question):
        query = f"{anchor} {question}"
        print(f"    [追问] 融合话题锚点检索: {query}")
        return kb.search(query, k=k)
    return kb.search(question, k=k)


def format_context(results) -> str:
    return "\n\n".join(f"[资料{r['id']}] {r['name']}\n{r['text']}" for r in results)


def format_sources(results) -> str:
    if not results:
        return ""
    src = "\n\n".join(f"**资料{r['id']}** | {r['name']}" for r in results)
    return f"### 🔍 本轮检索命中的资料\n\n{src}"


def qa_fn(question: str, history: list):
    """多轮问答（生成器）: 先推"问题+占位"让界面立刻响应, 再推最终答案。
    返回（清空输入框, 追加后的历史, 本轮命中的资料）"""
    history = list(history or [])
    question = (question or "").strip()
    if not question:
        yield "", history, gr.update()
        return

    # 话题锚点: 从历史里找最近一条带主体词的提问, 追问时拿它融合检索
    anchor = find_anchor(history)
    results = retrieve(question, anchor)

    # 本轮user消息只放变化内容（资料+问题）: 固定指令已经在QA_SYSTEM里, 不必每轮重复
    user_content = (f"【知识库资料】\n{format_context(results)}\n\n"
                    f"【用户问题】{question}")

    # 先拼messages再改history: 否则本轮问题会以"历史"身份重复发给模型
    messages = [{"role": "system", "content": QA_SYSTEM}]
    messages += trim_history(history)              # 历史消息: 问题/回答原文, 不带当时的资料块
    messages.append({"role": "user", "content": user_content})

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": "⏳ 正在检索并思考..."})
    yield "", history, ""

    try:
        answer = complete(messages)
    except Exception as e:                         # 网络/额度异常: 占位改成错误, 不让历史错位
        history[-1] = {"role": "assistant", "content": f"⚠️ 调用失败: {e}"}
        yield "", history, format_sources(results)
        return

    # 这里不追加DISCLAIMER: 历史里每轮都重复会污染后续轮次的上下文, 免责声明在界面底部常驻
    history[-1] = {"role": "assistant", "content": answer}
    yield "", history, format_sources(results)


def clear_fn():
    """新对话: 历史+输入框+资料面板一起清空"""
    return [], "", ""


def clear_chat_fn():
    """只清空对话记录（报告上下文保留, 还能接着问）"""
    return []


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


def material_block(e, j) -> str:
    """单条知识库资料块: 逐项解读、综合总结、追问上下文三处共用, 免得三份手抄"""
    it = e["item"]
    return (f"[资料{it['id']}] {it['name']}({'/'.join(it['abbr'])})\n"
            f"本次结果: {e['value']} {it['unit']}"
            f"({j['flag']}{j['arrow']}, 参考范围{j['lo']}-{j['hi']}, 来源{j['src']})\n"
            f"升高意义: {it['elevated_meaning']}\n"
            f"降低意义: {it['decreased_meaning']}\n"
            f"相关疾病: {'、'.join(it['related_diseases'])}\n"
            f"复检建议: {it['recheck_advice']}")


def build_report_context(parsed, skipped) -> str:
    """把整份报告打包成追问用的上下文（拼在 REPORT_CHAT_SYSTEM 之后）:
    事实表 + 异常项顺序 + 每项知识库资料。报告一定, 这一段就固定, 后续追问全程复用。
    异常顺序必须写清楚, 否则用户问"第2项异常"时模型对不上号。"""
    abnormals = [(e, j) for e, j in parsed if j["flag"] != "正常"]
    order = "\n".join(
        f"{i}. {e['item']['name']}({'/'.join(e['item']['abbr'])}) "
        f"{e['value']} {e['item']['unit']} {j['flag']}{j['arrow']}"
        for i, (e, j) in enumerate(abnormals, 1)) or "无异常项"
    materials = "\n\n".join(material_block(e, j) for e, j in parsed)
    return "\n\n".join([
        f"【本次报告指标】识别 {len(parsed)} 项, 异常 {len(abnormals)} 项\n"
        + parse_table(parsed, skipped),
        f"【异常项（按逐项解读的顺序）】\n{order}",
        f"【指标知识库资料】\n{materials}",
    ])


def report_fn(report_text: str):
    """生成器函数: 每完成一步就 yield 一次, 界面即时刷新。
    输出 4 件: 表格 Markdown / 解读 Markdown / 追问历史 / 追问用的报告上下文"""
    if not report_text.strip():
        yield "请先粘贴报告内容。", "", gr.update(), gr.update()
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
        yield ("未能识别任何指标。请检查格式: 每行应为「缩写 名称 数值 单位 范围」。",
               "", gr.update(), gr.update())
        return

    abnormals = [(e, j) for e, j in parsed if j["flag"] != "正常"]
    table_md = parse_table(parsed, skipped)
    # 新报告=新话题: 清空上一份报告的追问记录, 并换上这份报告的上下文
    chat_system = REPORT_CHAT_SYSTEM + "\n\n" + build_report_context(parsed, skipped)
    yield table_md, f"✅ 识别 {len(parsed)} 项, 异常 {len(abnormals)} 项, 开始逐项解读...", [], chat_system

    # ② 逐项解读 (流式追加)——build_prompt 已是"固定指令在前"的缓存友好结构
    all_md = ""
    for i, (e, j) in enumerate(abnormals, 1):
        it = e["item"]
        all_md += (f"\n\n---\n\n### 📌 异常{i}: {it['name']} "
                   f"{e['value']}{it['unit']}({j['flag']}{j['arrow']})\n\n")
        all_md += chat(build_prompt(e, j)) + DISCLAIMER
        yield table_md, all_md.strip(), gr.update(), gr.update()

    # ③ 综合总结 (资料必须随行——LLM每次调用都是无状态的)
    # 总结 prompt 复用 report_rag.build_summary_prompt, 消灭双份手抄
    if abnormals:
        materials = "\n\n".join(material_block(e, j) for e, j in abnormals)
        summary_prompt = build_summary_prompt(materials)
        all_md += "\n\n---\n\n# 📋 报告综合总结\n\n" + chat(summary_prompt) + DISCLAIMER
        yield table_md, all_md.strip(), gr.update(), gr.update()


def report_chat_fn(question: str, history: list, report_ctx: str):
    """报告追问: 历史/裁剪规则与问答页签一致, 只是 system 换成本次报告上下文。
    返回（清空输入框, 追加后的历史）"""
    history = list(history or [])
    question = (question or "").strip()
    if not question:
        yield "", history
        return
    if not report_ctx:
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant",
                        "content": "请先在上方粘贴报告并点「解析并解读」, 我才能就结果回答。"})
        yield "", history
        return

    messages = [{"role": "system", "content": report_ctx}]
    messages += trim_history(history)              # 历史消息: 问题/回答原文
    messages.append({"role": "user", "content": question})

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": "⏳ 正在思考..."})
    yield "", history

    try:
        answer = complete(messages)
    except Exception as e:                         # 网络/额度异常: 占位改成错误, 不让历史错位
        history[-1] = {"role": "assistant", "content": f"⚠️ 调用失败: {e}"}
        yield "", history
        return

    history[-1] = {"role": "assistant", "content": answer}
    yield "", history



with gr.Blocks(title="检验报告智能解读") as demo:
    gr.Markdown("# 🏥 检验报告智能解读系统\n基于本地知识库的RAG问答与报告解析|AI生成, 仅供参考")
    with gr.Tab("💬 指标问答"):
        chatbot = gr.Chatbot(
            label="对话（可以连续追问）",
            type="messages",
            height=420,
            show_copy_button=True,
            placeholder="先问一个问题, 例如: 最近总觉得没力气, 是不是贫血?",
        )
        with gr.Row():
            q = gr.Textbox(label="你的问题", placeholder="例如: 最近总觉得没力气, 是不是贫血?",
                           lines=2, scale=7, show_label=False)
            with gr.Column(scale=1, min_width=110):
                btn1 = gr.Button("提问", variant="primary")
                btn_clear = gr.Button("🆕 新对话", size="sm")
        src = gr.Markdown()
        gr.Markdown("⚠️ AI 生成内容不构成医疗建议, 不能替代专业医生判断。")
        btn1.click(qa_fn, inputs=[q, chatbot], outputs=[q, chatbot, src])
        q.submit(qa_fn, inputs=[q, chatbot], outputs=[q, chatbot, src])
        btn_clear.click(clear_fn, outputs=[chatbot, q, src])
    with gr.Tab("📋 报告解读"):
        rep = gr.Textbox(label="粘贴报告文本", value=SAMPLE_REPORT, lines=14)
        btn2 = gr.Button("解析并解读", variant="primary")
        table = gr.Markdown()
        interp = gr.Markdown()
        gr.Markdown("---\n### 💬 就这份报告追问\n解析完成后可在这里连续追问, 例如「第2项异常具体该怎么办?」「这些指标要不要紧?」")
        report_ctx = gr.State("")
        rep_chat = gr.Chatbot(
            label="追问记录",
            type="messages",
            height=340,
            show_copy_button=True,
            placeholder="先点上面的「解析并解读」, 再在这里追问",
        )
        with gr.Row():
            rep_q = gr.Textbox(label="你的问题", placeholder="例如: 第2项异常具体该怎么办?",
                               lines=2, scale=7, show_label=False)
            with gr.Column(scale=1, min_width=110):
                btn3 = gr.Button("追问", variant="primary")
                btn_rep_clear = gr.Button("🆕 新对话", size="sm")
        gr.Markdown("⚠️ AI 生成内容不构成医疗建议, 不能替代专业医生判断。")
        btn2.click(report_fn, inputs=rep, outputs=[table, interp, rep_chat, report_ctx])
        btn3.click(report_chat_fn, inputs=[rep_q, rep_chat, report_ctx], outputs=[rep_q, rep_chat])
        rep_q.submit(report_chat_fn, inputs=[rep_q, rep_chat, report_ctx], outputs=[rep_q, rep_chat])
        btn_rep_clear.click(clear_chat_fn, outputs=[rep_chat])

if __name__ == "__main__":
    demo.launch(inbrowser=True)
