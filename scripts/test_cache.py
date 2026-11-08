import os, time, sys
from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()
from report_rag import SYSTEM_PROMPT   # 直接用项目真实的系统提示词，最准

client = OpenAI(api_key=os.getenv("LLM_API_KEY"),
                base_url=os.getenv("LLM_BASE_URL"))

t0 = time.time()
r = client.chat.completions.create(
    model=os.getenv("LLM_MODEL"),
    messages=[{"role": "system", "content": SYSTEM_PROMPT},
              {"role": "user", "content": "血红蛋白 90g/L 说明什么？"}],
    temperature=0.2)
u = r.usage
hit  = getattr(u, "prompt_cache_hit_tokens", 0) or (u.model_extra or {}).get("prompt_cache_hit_tokens", 0)
miss = getattr(u, "prompt_cache_miss_tokens", 0) or (u.model_extra or {}).get("prompt_cache_miss_tokens", 0)
print(f"耗时{time.time()-t0:.1f}s | 命中{hit} | 未命中{miss} | 总输入{u.prompt_tokens}")
