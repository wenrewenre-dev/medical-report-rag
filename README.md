# 🏥 检验报告智能解读系统

基于本地医学知识库的 RAG 系统：粘贴化验报告 → 自动解析指标 → 逐项 AI 解读 → 跨指标综合总结；也支持自然语言自由问答。所有回答均引用知识库条目（[资料X]），知识库未覆盖的内容明确提示，不编造。

> ⚠️ AI 生成内容不构成医疗建议，不能替代专业医生判断。

## ✨ 特性

- **混合检索**：FAISS 向量检索 + BM25 关键词检索，加权 RRF 融合排序
- **报告结构化解析**：正则提取指标行，对照多人群参考区间自动判定偏高/偏低/危急值
- **双层解读**：异常项逐项解读 + 末尾跨指标综合总结（优先级排序、复查行动清单）
- **DeepSeek 前缀缓存优化**：固定指令前置的 prompt 结构，实测单次报告管线缓存命中率 **83.5%**（6528/7823 tokens），综合总结调用达 **95%**
- **报告解读逐项流式输出**

## 🚀 快速开始

~~~powershell
git clone https://github.com/wenrewenre-dev/medical-report-rag.git
cd lab-report-rag
python -m venv venv
venv\Scripts\Activate.ps1        # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # macOS/Linux: cp .env.example .env
python scripts/app.py            # 浏览器打开 http://127.0.0.1:7860
~~~

> 首次运行会自动下载中文嵌入模型（约 100MB，已配置 hf-mirror.com 加速），之后离线可用。

### 环境变量

复制 `.env.example` 为 `.env` 并填入自己的密钥：

~~~text
LLM_API_KEY=sk-你的DeepSeek密钥
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
~~~

## 📁 项目结构

~~~text
├── README.md
├── requirements.txt
├── .env.example            # 环境变量模板（不含真实密钥）
├── scripts/
│   ├── app.py              # Gradio Web 界面（问答/报告解读双页签）
│   ├── kb.py               # 检索层：FAISS + BM25 + 加权 RRF
│   ├── parse_report.py     # 报告文本解析 + 参考范围判定
│   ├── report_rag.py       # 报告解读管线：逐项解读 + 综合总结（CLI）
│   ├── build_index.py      # 构建 FAISS 向量索引
│   ├── append_batch.py     # 知识库批量追加
│   ├── validate_kb.py      # 知识库条目校验
│   ├── eval_retrieval.py   # 检索质量评测
│   ├── test_llm.py         # LLM 连通性测试
│   ├── test_cache.py       # 缓存命中测试
│   ├── test_cache_retry.py # 缓存落盘等待重试测试
│   ├── test_cache_v2.py    # 生产形态缓存测试（固定前缀+变化尾部）
│   ├── search_test.py      # 检索单测
│   └── rag_demo.py         # 早期演示脚本
└── data/
    ├── kb.json             # 医学知识库（指标/参考区间/临床意义/复检建议）
    ├── faiss.index         # 向量索引
    └── meta.json           # 索引元数据
~~~

## 🧪 检索质量评测

~~~powershell
python scripts/eval_retrieval.py
~~~

18 条评测问题分三组实测：**17/18、14/18、17/18**；未命中的个别案例为口语化表述的已知边界案例，未发现新增退化。

## 🧠 缓存友好设计约定

1. 固定指令在前、变化内容在后（system → user 固定模板 → 变化数据）
2. DeepSeek 缓存以 64 tokens 为存储单元，须完整匹配前缀单元才命中
3. 每次任务前 1-2 次调用 miss = 缓存落盘，属正常；从第 2-3 次起命中爬坡
4. 修改 SYSTEM_PROMPT / 指令模板后缓存键全变，首次运行 miss 属预期

复现缓存测试：

~~~powershell
python scripts/test_cache_v2.py
~~~

## 🛠 技术栈

Gradio · sentence-transformers（中文嵌入模型）· faiss-cpu · rank-bm25 · OpenAI SDK（DeepSeek API）· python-dotenv
