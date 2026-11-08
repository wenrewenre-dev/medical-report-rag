# test_cache_retry.py
import os, time, sys
from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()
from report_rag import SYSTEM_PROMPT

client = OpenAI(api_key=os.getenv("LLM_API_KEY"),
                base_url=os.getenv("LLM_BASE_URL"))

for i in range(10):
    r = client.chat.completions.create(
        model=os.getenv("LLM_MODEL"),
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": "血红蛋白 90g/L 说明什么？"}],
        temperature=0.2)
    u = r.usage
    extra = u.model_extra or {}
    hit = extra.get("prompt_cache_hit_tokens", 0) or 0
    print(f"第{i+1}次：命中{hit} | 未命中{extra.get('prompt_cache_miss_tokens', 0)} | 总输入{u.prompt_tokens}")
    if hit > 0:
        print("✅ 缓存已落盘并命中，链路闭环")
        break
    time.sleep(60)
