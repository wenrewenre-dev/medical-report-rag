# scripts/api.py —— FastAPI + SSE 后端
#
# 定位：Gradio 是演示工具，这里是生产形态的接口层。
# 关键点是"不重写任何 AI 逻辑"——直接复用 app.py 的 qa_fn / report_fn 生成器，
# 只把它们的同步 yield 桥接成 SSE 事件流。前端换成 React / 小程序 / 桌面端都不用动后端。
#
# 事件协议（每个事件都带 event 名，data 是 JSON）：
#   start   {question} 或 {chars}      流开始
#   sources {markdown}                 /api/qa 专用：本轮命中的资料 + 改写查询
#   table   {markdown}                 /api/report 专用：解析出的指标表
#   delta   {text}                     增量正文（前端直接 append）
#   done    {answer} 或 {markdown}     完整结果（便于前端校正）
#   error   {message}                  异常
#
# 启动：python scripts/api.py    → http://127.0.0.1:7862/
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import app as core                       # 复用同一套管线（KB 只加载一次）

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")

api = FastAPI(title="检验报告智能解读 API", version="1.0.0")

# 前后端分离：前端可能跑在别的端口/域名，给演示用的宽松 CORS
api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


class QARequest(BaseModel):
    question: str
    use_rewrite: bool = False
    history: list[dict] = []


class ReportRequest(BaseModel):
    report_text: str
    keep_age: bool = True


class ReportChatRequest(BaseModel):
    """报告追问：context 来自 /api/report 的 done 事件，原样回传即可。
    上下文由客户端持有，服务端不存任何会话状态——这才叫前端可换。"""
    question: str
    context: str
    history: list[dict] = []


def sse(name: str, payload: dict) -> dict:
    return {"event": name, "data": json.dumps(payload, ensure_ascii=False)}


_SENTINEL = object()


def _next(gen):
    """线程里取下一帧；StopIteration 不能穿过线程边界，用哨兵代替"""
    try:
        return next(gen)
    except StopIteration:
        return _SENTINEL


def _delta(prev: str, cur: str) -> str:
    """生成器给的是"到目前为止的全文"，前端要的是增量"""
    return cur[len(prev):] if cur.startswith(prev) else cur


@api.get("/api/health")
def health():
    return {"status": "ok", "kb_items": len(core.kb.meta),
            "ocr": core.ocr.available(), "rewrite": core.REWRITE_STRATEGY}


@api.post("/api/qa")
async def api_qa(req: QARequest):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")

    async def stream():
        yield sse("start", {"question": question})
        gen = core.qa_fn(question, req.history or [], req.use_rewrite)
        prev, sent_sources = "", False
        try:
            while True:
                item = await asyncio.to_thread(_next, gen)   # 生成器跑在线程里, 不阻塞事件循环
                if item is _SENTINEL:
                    break
                _, history, src = item
                # 资料面板只会出现一次；gr.update() 这类占位对象按 dict 处理直接跳过
                if not sent_sources and isinstance(src, str) and src:
                    yield sse("sources", {"markdown": src})
                    sent_sources = True
                if history and history[-1]["role"] == "assistant":
                    cur = history[-1]["content"]
                    if cur and "⏳" not in cur and cur != prev:
                        chunk = _delta(prev, cur)
                        prev = cur
                        if chunk:
                            yield sse("delta", {"text": chunk})
        except Exception as e:                         # 生成器炸了也要给前端一个体面的收尾
            yield sse("error", {"message": f"{type(e).__name__}: {e}"})
        yield sse("done", {"answer": prev})

    return EventSourceResponse(stream())


@api.post("/api/report")
async def api_report(req: ReportRequest):
    text = (req.report_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="report_text 不能为空")

    async def stream():
        yield sse("start", {"chars": len(text)})
        gen = core.report_fn(text, req.keep_age)
        prev, sent_table, report_ctx = "", False, ""
        try:
            while True:
                item = await asyncio.to_thread(_next, gen)
                if item is _SENTINEL:
                    break
                table_md, interp_md, _, ctx = item
                if isinstance(ctx, str) and ctx:          # 首帧拿到后续追问要用的上下文
                    report_ctx = ctx
                if not sent_table and isinstance(table_md, str) and table_md:
                    yield sse("table", {"markdown": table_md})
                    sent_table = True
                if isinstance(interp_md, str) and interp_md != prev:
                    chunk = _delta(prev, interp_md)
                    prev = interp_md
                    if chunk:
                        yield sse("delta", {"text": chunk})
        except Exception as e:
            yield sse("error", {"message": f"{type(e).__name__}: {e}"})
        # context 是后续 /api/report/chat 的"票据"，约 1.3 万字；不需要追问的客户端忽略即可
        yield sse("done", {"markdown": prev, "context": report_ctx})

    return EventSourceResponse(stream())


@api.post("/api/report/chat")
async def api_report_chat(req: ReportChatRequest):
    """报告追问：把 /api/report 返回的 context 原样带回来，历史也由客户端持有"""
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")
    if not (req.context or "").strip():
        raise HTTPException(status_code=400,
                            detail="context 不能为空：先调用 /api/report，保存 done 事件里的 context")

    async def stream():
        yield sse("start", {"question": question})
        gen = core.report_chat_fn(question, req.history or [], req.context)
        prev = ""
        try:
            while True:
                item = await asyncio.to_thread(_next, gen)
                if item is _SENTINEL:
                    break
                _, history = item
                if history and history[-1]["role"] == "assistant":
                    cur = history[-1]["content"]
                    if cur and "⏳" not in cur and cur != prev:
                        chunk = _delta(prev, cur)
                        prev = cur
                        if chunk:
                            yield sse("delta", {"text": chunk})
        except Exception as e:
            yield sse("error", {"message": f"{type(e).__name__}: {e}"})
        yield sse("done", {"answer": prev})

    return EventSourceResponse(stream())


@api.get("/")
def demo_page():
    """自带的极简前端：只演示怎么消费 SSE，真正的客户端可以随便换"""
    page = os.path.join(STATIC, "demo.html")
    if not os.path.exists(page):
        return {"hint": "访问 /docs 查看接口，或 POST /api/qa 与 /api/report"}
    return FileResponse(page)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(api, host="127.0.0.1", port=7862, log_level="info")
