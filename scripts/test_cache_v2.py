# test_cache_v2.py —— 模拟生产形态：固定长前缀 + 变化的尾部
import os, sys
from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()
from report_rag import SYSTEM_PROMPT

client = OpenAI(api_key=os.getenv("LLM_API_KEY"),
                base_url=os.getenv("LLM_BASE_URL"))

# 固定模板：越长越好，建议 300-500 字（可以直接从你 report_rag.py 的 user 模板里复制扩充）
TEMPLATE = """【解读要求】
1. 只依据参考资料作答，每条结论标注 [资料X] 引用
2. 解读顺序：先判断指标状态，再解释临床意义，最后给复查建议
3. 复查建议需包含紧迫度（数天内 / 2-4 周 / 2-12 周）
4. 资料未覆盖的内容明确说明"知识库未覆盖"，不得编造
5. 回答末尾固定附免责声明：本解读由 AI 生成，仅供参考，不能替代专业医疗建议
6. 语言风格：面向无医学背景的普通人，避免堆砌术语，必要时用比喻解释
7. 若指标仅轻微偏离参考范围，明确说明"轻微偏离"并安抚，不要夸大严重性
8. 涉及多个指标关联判断时（如贫血相关参数），需提示用户结合完整报告综合判断
"""

QUESTIONS = ["血红蛋白 90g/L 说明什么？",
             "白细胞 12.5×10^9/L 要紧吗？",
             "血小板 350×10^9/L 正常吗？",
             "空腹血糖 6.8 mmol/L 怎么解读？"]

for i, q in enumerate(QUESTIONS, 1):
    r = client.chat.completions.create(
        model=os.getenv("LLM_MODEL"),
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": f"{TEMPLATE}\n【待解读指标】{q}"}],
        temperature=0.2)
    u = r.usage
    extra = u.model_extra or {}
    hit = getattr(u, "prompt_cache_hit_tokens", 0) or extra.get("prompt_cache_hit_tokens", 0)
    print(f"第{i}问: 命中{hit} | 未命中{u.prompt_tokens - hit} | 总输入{u.prompt_tokens}")
