# scripts/rag_demo.py —— 第4步验收：最小RAG完整闭环
import os
from dotenv import load_dotenv
from openai import OpenAI

from kb import KB  # 导入同目录的kb.py（运行时必须在项目根目录）

load_dotenv()

# 系统提示词 = 给LLM立的规矩，是RAG防幻觉的第一道闸
SYSTEM_PROMPT = """你是检验报告解读助手，面向非医学专业用户。

回答规则（必须全部遵守）：
1. 只依据【参考资料】中的内容回答，禁止编造资料里没有的医学事实。
2. 引用资料时在句末标注来源编号，格式如：[资料6]。
3. 如果资料不足以回答，明确说明"知识库暂未收录该项目"；之后可给一般性建议，但必须注明"此建议不来自知识库"。
4. 只做指标解读和就医方向建议，不下诊断、不推荐具体药物，异常值建议咨询医生。
5. 用通俗中文回答，医学术语首次出现时用括号简单解释。
"""

# 免责声明由代码拼接，保证100%出现（合规红线，不指望模型自觉）
DISCLAIMER = "\n\n——\n⚕️ 免责声明：以上内容由AI基于公开医学资料生成，仅供参考，不能替代专业医疗建议。如有异常请及时就医。"

def build_user_prompt(question: str, results: list) -> str:
    """把检索资料和问题组装成一条user消息"""
    blocks = [f"[资料{r['id']}] {r['text']}" for r in results]
    return "【参考资料】\n" + "\n\n".join(blocks) + "\n\n【用户问题】\n" + question

def main():
    kb = KB()
    client = OpenAI(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
    )
    print("✅ 最小RAG已就绪（输入问题后回车；直接回车退出）")

    while True:
        question = input("\n❓ 你的问题：").strip()
        if not question:
            break

        # ① 检索：先让用户看到"开卷考试的参考资料"
        results = kb.search(question, k=3)
        print("\n📎 检索到的资料：")
        for r in results:
            print(f"   [资料{r['id']}] {r['name']}（相似度 {r['score']:.3f}）")

        # ② 拼prompt → 调LLM
        response = client.chat.completions.create(
            model=os.getenv("LLM_MODEL"),
            temperature=0.2,  # 事实性解读用低随机度，回答更稳定
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(question, results)},
            ],
        )
        answer = response.choices[0].message.content
        print("\n💬 解读：")
        print(answer + DISCLAIMER)

if __name__ == "__main__":
    main()
