# 🏥 检验报告智能解读系统

基于本地医学知识库的 RAG 系统：粘贴化验报告 → 自动解析指标 → 逐项 AI 解读 → 跨指标综合总结；也支持自然语言自由问答，并可连续追问。所有回答均引用知识库条目（[资料X]），知识库未覆盖的内容明确提示，不编造。

> ⚠️ AI 生成内容不构成医疗建议，不能替代专业医生判断。

## ✨ 特性

- **混合检索**：FAISS 向量检索 + BM25 关键词检索，加权 RRF 融合排序
- **报告结构化解析**：正则提取指标行，对照多人群参考区间自动判定偏高/偏低/危急值
- **双层解读**：异常项逐项解读 + 末尾跨指标综合总结（优先级排序、复查行动清单）
- **DeepSeek 前缀缓存优化**：固定指令前置的 prompt 结构，实测单次报告管线缓存命中率 **83.5%**（6528/7823 tokens），综合总结调用达 **95%**
- **报告解读逐项流式输出**；问答与报告追问的回答均逐段流式生成
- **多轮追问**：`gr.Chatbot` 保留对话历史，问答页签带话题锚点检索，报告解读页签可就本次报告追问
- **拍照 / PDF 入口**：电子版 PDF 直接抽文字层，扫描件与手机照片走 OCR，识别结果填进文本框再进解析管线
- **查询改写 / HyDE**：检索前让 LLM 把口语问题改写成多条检索式，多查询 RRF 融合；18 条回归集 HIT@1 从 17/18 提到 18/18
- **报告脱敏**：解析前抹掉姓名/身份证/病历号等 PHI，LLM 只看到指标数据；年龄可配、落盘可审计
- **LLM 裁判**：自动审核"引用是否真实、结论是否有据、数字是否编造"，18 条真实回答 + 18 条注入缺陷标定全通过
- **FastAPI + SSE**：`/api/qa`、`/api/report` 两条流式接口，前端换成 React / 小程序 / 桌面端都不用动后端

## 🚀 快速开始

~~~powershell
git clone https://github.com/wenrewenre-dev/medical-report-rag.git
cd medical-report-rag
python -m venv venv
venv\Scripts\Activate.ps1        # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # macOS/Linux: cp .env.example .env
python scripts/app.py            # 浏览器打开 http://127.0.0.1:7860
~~~

> 国内装包慢的话加个镜像源：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
> 不想折腾 Python 环境，也可以直接用下面的 [Docker 部署](#-docker-部署零基础版)（一条命令起服务）。

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
├── requirements.txt        # Windows 本机环境（pip freeze）
├── requirements-docker.txt # 容器用依赖（Linux / CPU 推理，已核对轮子）
├── Dockerfile              # python:3.12-slim + CPU 版 torch（pip 走清华源）
├── docker-compose.yml      # ui(7860) + api(7862)，模型走 named volume
├── .dockerignore
├── .env.example            # 环境变量模板（不含真实密钥）
├── scripts/
│   ├── app.py              # Gradio Web 界面（多轮问答/报告解读双页签）
│   ├── api.py              # FastAPI + SSE 接口（复用同一套管线）
│   ├── static/demo.html    # 原生 HTML 的 SSE 消费示例
│   ├── ocr_report.py       # 拍照/PDF → 文本（文字层优先，扫描件走 OCR）
│   ├── kb.py               # 检索层：FAISS + BM25 + 加权 RRF
│   ├── query_rewrite.py    # 查询改写 / HyDE：口语问题 → 多条检索查询
│   ├── parse_report.py     # 报告文本解析 + 参考范围判定
│   ├── anonymize.py        # 报告脱敏：解析前抹掉姓名/身份证/病历号等 PHI
│   ├── report_rag.py       # 报告解读管线：逐项解读 + 综合总结（CLI）
│   ├── build_index.py      # 构建 FAISS 向量索引
│   ├── append_batch.py     # 知识库批量追加
│   ├── validate_kb.py      # 知识库条目校验
│   ├── eval_retrieval.py   # 检索质量评测（HIT@k / MRR，可对比查询改写）
│   ├── judge.py            # LLM 裁判：引用真实性 / 结论支持度 / 数字编造
│   ├── eval_judge.py       # 回答质量自动评测（含注入缺陷标定）
│   ├── test_llm.py         # LLM 连通性测试
│   ├── test_anonymize.py   # 脱敏回归测试（含 prompt 泄漏检查）
│   ├── test_judge.py       # 裁判解析/兜底的离线单测（不花钱）
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

## 📷 拍照 / PDF 识别

报告解读页签顶部有「📷 拍照 / PDF 识别」入口：上传照片或 PDF 后直接进解析管线。三条路径按代价从低到高挑：

| 输入 | 处理 | 依赖 |
|---|---|---|
| 电子版 PDF（有文字层） | `pypdf` 直接抽文字，零误差，不跑 OCR | pypdf |
| 扫描件 PDF | `pymupdf` 按 200dpi 渲染 → OCR | pymupdf |
| 手机拍照 | 直接 OCR | rapidocr-onnxruntime |

- **先给文本再解读**：识别结果先填进「粘贴报告文本」框（默认勾选「识别后立即解读」）；把勾去掉就能先核对识别有没有错，再手动点「解析并解读」
- **识别不出来就明说**：空白页、糊图会提示重新拍摄，不会拿半截文本硬跑管线
- **依赖可选**：没装 OCR 依赖时入口照常显示，点击给出补装命令，纯文本粘贴用法不受影响
- **局限**：OCR 对反光、倾斜、小字仍会认错；医学数值容不得错，所以留了"识别结果可见、可核对"这一步

## 💬 多轮对话设计

两个页签都用 `gr.Chatbot(type="messages")` 保存历史，可连续追问，回答均流式生成：`stream_answer` 每攒够 6 个字刷新一次界面，中途断流保留已生成内容并补提示。

### 指标问答

- **历史**：`[{"role": "user"/"assistant", "content": ...}]` 列表，界面显示与送进 LLM 的是同一份数据；「🆕 新对话」一键清空
- **追问检索**：问题里认不出知识库主体词时（"那需要复查什么?" "能吃什么?"），把「话题锚点」——最近一条认得出主体词的提问——拼进检索 query 再检索；问题自带主体词（"血糖多少算高?"）时只按本轮检索，避免被旧话题带偏
- **历史窗口**：最多带最近 `MAX_TURNS=6` 轮 + 6000 字预算，超出时从最早的轮次整对丢弃，保证 user/assistant 不错位
- **异常兜底**：LLM 调用失败也补一条 assistant 占位，避免下一轮历史错位
- **免责声明常驻**：问答页签只在聊天框下方显示一次，不逐条追加——避免每轮声明挤进历史、污染后续追问（报告解读页签仍逐条追加）
- **资料面板**：检索结果先于答案出现，流式过程中不重发（`gr.update()` 占位）

### 报告解读

- **上下文**：解析完成后把「事实表 + 异常项顺序 + 每项知识库资料」打包成该会话固定的 system prompt（存在 `gr.State` 里），追问时只追加问题本身，不重复塞资料
- **异常顺序**：上下文写明「异常1/2/3…」的先后，用户问"第2项异常具体该怎么办?"时能对上号
- **新报告即新话题**：重新解析会清空追问记录并换上新的报告上下文；「🆕 新对话」只清记录、保留报告
- **实测**：样例报告上下文约 6.8k input tokens，首次追问 miss（落盘），第二轮命中 6656/7258 ≈ 92%；首段文字 3.0s 到达、整段 5.2s

## 🔀 查询改写 / HyDE

`scripts/query_rewrite.py` 在检索之前把问题变成"检索友好"的样子：

- **rewrite**：让 LLM 把口语问题改写成 3 条检索式，覆盖项目全名 / 缩写 / 俗称
- **hyde**：先让 LLM 写一段假设性的知识库条目（Hypothetical Document Embeddings），再拿这段内容去检索——短问句缺的正是上下文

每个变体各自检索，最后用同一套加权 RRF 合并（原问题权重 1.0、变体 0.6）。改写失败一律退回原问题，检索不会因为多一次 LLM 调用而不可用。

~~~powershell
python scripts/eval_retrieval.py --strategies off,rewrite,hyde,both
~~~

### 实测（18 条回归集，hybrid 检索路径）

| 策略 | HIT@1 | HIT@5 | MRR |
|---|---|---|---|
| off（基线） | 17/18 | 18/18 | 0.972 |
| **rewrite** | **18/18** | 18/18 | **1.000** |
| hyde | 17/18 | 18/18 | 0.972 |
| both（改写 + HyDE） | 17/18 | 18/18 | 0.972 |

- 拉开差距的正是那条硬骨头「最近总觉得没力气，是不是贫血」：基线 Top3 是 **RDW / 血红蛋白 / MCH**，改写后变成 **血红蛋白 / MCH / MCHC**，RDW 掉出前三。纯症状提问没有指标名可抓，只能靠改写把"贫血"落到"血红蛋白"上
- 同一配置连跑 3 次均为 18/18、MRR 1.000，改写内容每次不同但结论稳定
- HyDE 的收益出现在**纯语义**路径（vector 基线 17/18 → 18/18、MRR 0.956 → 1.000），在 hybrid 上被 BM25 路覆盖，与改写叠加反而互相稀释——所以界面默认只用 rewrite
- 本集 HIT@5/@10 基线已经是 18/18，天花板效应明显：提升只能体现在 HIT@1/MRR。企业级数据上"多改写策略 union 提升 HIT@10 十余个点"的结论，在这个 40 条知识库、18 条测试集的规模上验证不出来

界面：问答页签的「查询改写（检索增强）」默认开启（多一次 LLM 调用，实测约 +1.6 秒），取消勾选即退回单查询检索；命中资料面板会把本轮改写式摊开展示，方便判断"检索不准是改写背锅还是检索背锅"。

> 口径说明：RRF 候选池固定为 `CANDIDATES=30`，不随 `k` 变化——否则 `k=3`（界面）和 `k=10`（评测）会因池深不同排出不同名次，评测和应用就对不上了（第一版正是踩了这个坑：评测说 18/18，界面里 RDW 仍排第一）。

## 🔒 报告数据脱敏

解析之前先抹掉 PHI，只让指标数据进管线（`scripts/anonymize.py`）：

| 抹掉 | 保留标签 |
|---|---|
| 姓名、身份证号、手机/座机、邮箱 | `姓名：[已脱敏]` |
| 病历号、门诊/住院/就诊号、样本/条码/检验号 | `病历号：[已脱敏]` |
| 住址、出生日期、采样/报告日期 | `采样时间：[已脱敏]` |

- **只抹值、留标签**：行结构不变（`姓名：[已脱敏]  性别：男  年龄：35`），`parse_line` 照常逐行解析
- **性别必须保留、年龄可配**：性别决定用哪套参考区间（功能必需）；年龄默认保留（不参与判定但对解读有用），在报告页签取消勾选「脱敏时保留年龄」即可一并抹掉
- **接入点在解析入口**：`report_fn` 一进来就脱敏，所以逐项解读、综合总结、追问上下文（每轮都会随请求发出）都不含 PHI；OCR 识别出来的文本同样过这一层
- **问答输入也过一遍**：用户可能把整段报告贴进问题框——界面显示原文，送进检索和模型的是脱敏版，历史里的旧问题也会在发送前重新脱敏
- **审计落盘**：每次脱敏往 `data/anonymize_audit.jsonl` 追加一行 `{ts, kind, total, counts}`，只记类别和处数，不记原值（连哈希都不存，避免可逆）；写失败只告警，不影响主流程
- **不误伤指标**：`HGB  血红蛋白  112  g/L  130-175` 这类行一字不动，改完仍是 14 项、性别区间照常命中
- **界面文本框保留原文**：那是你自己的屏幕，留着方便核对 OCR 认没认错；只在送进管线那一刻脱敏

验证（`python scripts/test_anonymize.py`）：把每一次 `chat()` 的 messages 抓下来，断言里面不出现任何一个 PHI 原值——包括追问轮次和问答页签的输入；同时校验审计文件里也没有原值。

> 定位：本地部署是"数据不出机器"的被动防御，脱敏是"就算发出去也不含身份信息"的主动防御。两层都做，报告里那串样本号/门诊号才不会随请求进入供应商的日志。

## 🐳 Docker 部署（零基础版）

> ⚠️ 这套配置**没在开发机上构建验证过**：开发机没有管理员权限装不了 Docker，且 Docker Hub 在本网络不可达。但镜像源、依赖轮子都逐个实测过（数字见本节末尾）。首次构建请留意日志，报错发我。

### 第 0 步：确认系统

Windows 10（2004 以上）或 Windows 11，64 位。

### 第 1 步：装 WSL2（Linux 子系统）

1. `Win` 键 → 输入 `powershell` → 右键「Windows PowerShell」→ **以管理员身份运行**
2. 粘贴并回车：

   ~~~powershell
   wsl --install
   ~~~

3. 提示重启就**重启电脑**
4. 重启后会自动弹出 Ubuntu 窗口，设置用户名和密码（输密码时屏幕不显示，是正常的）

### 第 2 步：装 Docker Desktop

1. 仍然是**管理员** PowerShell：

   ~~~powershell
   winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
   ~~~

   （或者浏览器打开 https://www.docker.com/products/docker-desktop/ 下载 exe 双击安装）
2. **重启电脑**
3. 开始菜单打开 Docker Desktop，等左下角变绿（首次启动 1–2 分钟）

### 第 3 步：验证装好了

~~~powershell
docker --version
docker compose version
docker run --rm hello-world
~~~

最后一条打印出 `Hello from Docker!` 就算成功。

### 第 4 步：配镜像加速（**必须**，否则拉不到基础镜像）

Docker Desktop → 右上角齿轮 → **Docker Engine**，把右侧 JSON 改成：

~~~json
{
  "registry-mirrors": ["https://dockerproxy.net", "https://docker.1panel.live"]
}
~~~

点 **Apply & Restart**，等它重启完。验证：

~~~powershell
docker info | Select-String -Pattern "Registry Mirrors" -Context 0,2
~~~

能看到这两个地址就对了。

### 第 5 步：启动项目

~~~powershell
cd C:\Users\wenre\report-rag
copy .env.example .env
notepad .env
~~~

把 `LLM_API_KEY=` 后面换成你的 DeepSeek key，保存关闭。然后：

~~~powershell
docker compose up -d --build
~~~

首次构建 10–20 分钟（torch 约 178MB + 其余依赖），**看到 `Started` 才算成功**。进度可以看：

~~~powershell
docker compose logs -f api
~~~

### 第 6 步：打开用

| 入口 | 地址 |
|---|---|
| 界面 | http://127.0.0.1:7860 |
| 接口文档 | http://127.0.0.1:7862/docs |

### 常用命令

| 想做什么 | 命令 |
|---|---|
| 看状态 | `docker compose ps` |
| 看日志 | `docker compose logs -f api` |
| 改完代码重启 | `docker compose up -d --build` |
| 停止 | `docker compose stop` |
| 停止并删除容器 | `docker compose down` |
| 连模型缓存一起删 | `docker compose down -v` |

### 卡住了怎么办

| 现象 | 原因 / 处理 |
|---|---|
| `wsl --install` 报 `0x80370102` | BIOS 没开虚拟化，开机进 BIOS 打开 VT-x / AMD-V |
| `docker run hello-world` 超时 | 第 4 步没生效，重做并确认 `docker info` 里能看到 Registry Mirrors |
| 构建卡在 `pip install` | 换源：`docker compose build --build-arg PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple` |
| 7860 / 7862 端口被占用 | 改 `docker-compose.yml` 里 `"7860:7860"` 冒号左边的数字 |
| 打开 7860 是空白页 | `docker compose logs ui` 看报错，多半是 `.env` 里的 key 没填 |

### 实测数据（写进配置的依据）

| 项 | 数值 |
|---|---|
| PyPI 镜像速度 | 清华 9.65MB/s、腾讯 9.76MB/s（直连 pypi.org 在这网络只有 20KB/s） |
| torch CPU 轮子 | 178MB，阿里镜像约 3MB/s |
| 依赖版本 | 19 项逐个核对过 Linux/py3.12 轮子可用 |
| 基础镜像 | `python:3.12-slim`，必须先配镜像加速才拉得到 |

<details>
<summary>技术细节（点开）</summary>

- **模型不进镜像**：首次启动下载到 named volume `hf-cache`（485MB），重建镜像、重启都复用
- **data/ 用 bind mount**：改 `kb.json` 重启即生效，脱敏审计日志落在宿主机
- **torch 必须用 CPU 版**：PyPI 上的 Linux torch 带 CUDA，会多塞 2~5GB 的 nvidia 依赖；镜像默认从阿里 `pytorch-wheels/cpu` 取，可用 `--build-arg TORCH_INDEX_URL=...` 换源
- **依赖隔离**：`requirements-docker.txt`（Linux/容器）与 `requirements.txt`（Windows 本机）互不污染
- **非 root + HEALTHCHECK**：容器内以 uid 1000 运行，健康检查打 `/api/health`

</details>

## 🔌 FastAPI + SSE 后端

Gradio 是演示工具，`scripts/api.py` 是生产形态的接口层：直接复用 `qa_fn` / `report_fn` / `report_chat_fn` 的生成器，只把同步 `yield` 桥接成 SSE 事件流，**一行 AI 逻辑都没重写**——当初"界面层不写 AI 逻辑"那条原则的又一次兑现。

~~~powershell
python scripts/api.py     # http://127.0.0.1:7862 ，自带演示页 / 接口文档 /docs
~~~

~~~bash
curl -N -X POST http://127.0.0.1:7862/api/qa \
  -H "Content-Type: application/json" \
  -d '{"question":"最近总觉得没力气，是不是贫血","use_rewrite":true}'
~~~

### 三条路由

| 路由 | 用途 |
|---|---|
| `POST /api/qa` | 流式问答（支持 `use_rewrite` / `history`） |
| `POST /api/report` | 报告解析 + 逐项解读，`done` 事件里附带追问用的 `context` |
| `POST /api/report/chat` | 就本次报告追问，`context` 由客户端回传 |

### 追问闭环（服务端零状态）

`/api/report` 的 `done` 事件会带回 `context`（本次报告打包成的 system 上下文，两三项指标的小报告约 2.5k 字，样例大报告约 1.3 万字）。客户端保存它，追问时原样放回请求体：

~~~bash
curl -N -X POST http://127.0.0.1:7862/api/report/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"第2项异常具体该怎么办？","context":"<上一步的 done.context>","history":[]}'
~~~

历史同样由客户端持有（`[{"role","content"}]`），服务端不存任何会话状态——多实例部署、水平扩容都不用粘性会话。

### 事件协议

| 事件 | data | 说明 |
|---|---|---|
| `start` | `{question}` 或 `{chars}` | 流开始 |
| `sources` | `{markdown}` | `/api/qa`：本轮资料 + 改写查询 |
| `table` | `{markdown}` | `/api/report`：解析出的指标表 |
| `delta` | `{text}` | 增量正文，前端直接 append |
| `done` | `{answer}` / `{markdown, context}` | 完整结果（报告路由附带追问上下文） |
| `error` | `{message}` | 异常 |

- **不阻塞事件循环**：同步生成器每取一帧都走 `asyncio.to_thread`，多人同时提问不会互相卡住
- **前端随便换**：`/` 是自带的一百多行原生 HTML 演示（`fetch` + `ReadableStream` 手工解析 SSE，含追问闭环），换 React / 小程序 / 桌面端只要保留那段解析
- **KB 只加载一次**：API 与 Gradio 都 import 同一套 `kb` / `qa_fn` / `report_fn`
- **实测**：`/api/qa` 一条问答 116 个事件，首段增量 3.4s、整段 6.2s；`/api/report/chat` 追问 106 个事件，首段 3.6s、整段 6.0s；两条路由的 `delta` 拼接结果都与 `done` 完全一致
- **参数校验**：空问题/空报告/空 context 返回 400，缺字段返回 422（FastAPI 自动）

## ⚖️ LLM-as-a-Judge 回答评测

人工标注只够给检索做 18 条；要把评测扩到 100+，就让 LLM 当裁判（`scripts/judge.py`）。它按三项审核回答：

1. **引用真实性**：回答里的 `[资料X]` 是否都真在检索资料里。这一项另用正则做机器复核，裁判看漏会被标成 `citation_agree=false`
2. **结论支持度**：结论能否在资料里找到依据
3. **数字编造**：检验数值、参考范围、百分比是否都有出处

~~~powershell
python scripts/eval_judge.py --limit 5      # 冒烟
python scripts/eval_judge.py --calibrate    # 18 条全跑 + 注入缺陷标定
~~~

评测走真实链路：直接驱动 `app.qa_fn`，和界面上点「提问」是同一条管线。

### 实测（18 条回归集）

| 项目 | 结果 |
|---|---|
| 真实回答通过 | 18/18 |
| 引用项与机器复核一致 | 18/18 |
| 注入「假引用」被判不合格 | 6/6 |
| 注入「无依据结论」被判不合格 | 6/6 |
| 注入「编造数字」被判不合格 | 6/6 |

标定做法：拿合格回答改坏——把 `[资料1]` 换成不存在的 `[资料99]`、追加资料里没有的用药建议、把参考范围改成 `100-110 g/L`——再看裁判能否判不合格。18 条改坏样本全部被抓住，与人工标注 100% 一致。

**踩过的坑**：裁判的 `max_tokens` 不能卡太紧。推理模型的思维链 token 也计入这个预算，设成 600 时会出现"推理吃光预算、正文为空"的假失败（表现为裁判返回空字符串）；调到 1500 后消失。这类失败单独计为"解析失败"，不计入通过率分母，避免污染结论。

> 局限：LLM 裁判有位置偏好和"看着像对"的倾向，标定集也是合成缺陷。它适合当**回归护栏**（挡住明显退步），不能替代人工抽检。

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
5. 多轮会话的公共前缀只有 system 段：每轮 user 消息都带当轮资料块，历史里只留问题/回答原文，追问轮命中率低于报告管线属正常

复现缓存测试：

~~~powershell
python scripts/test_cache_v2.py
~~~

## 🛠 技术栈

Gradio · FastAPI（SSE）· sentence-transformers（中文嵌入模型）· faiss-cpu · rank-bm25 · RapidOCR · OpenAI SDK（DeepSeek API）· Docker Compose
