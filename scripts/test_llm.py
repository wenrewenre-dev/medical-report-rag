# scripts/test_llm.py —— 第1步验收脚本：验证LLM API能正常调通
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # 读取.env里的密钥

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
)

response = client.chat.completions.create(
    model=os.getenv("LLM_MODEL"),  # 从.env读取，现在就是免费的 glm-4.7-flash
    messages=[
        {"role": "user", "content": "用一句话解释什么是RAG（检索增强生成）。"},
    ],
)

print(response.choices[0].message.content)
