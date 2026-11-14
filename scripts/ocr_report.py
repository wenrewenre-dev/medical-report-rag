# scripts/ocr_report.py — OCR 入口：报告照片 / PDF → 文本
# 原则同解析层：确定性代码干活，不用 LLM 猜；识别不出来的就交给下游的"未能识别"提示
#
# 三条路径，按代价从低到高：
#   1. PDF 有文字层的（电子版报告）→ pypdf 直接抽，零误差，不需要 OCR
#   2. PDF 是扫描件的 → pymupdf 渲染成图 → RapidOCR
#   3. 手机拍照 → RapidOCR
# 依赖全用延迟导入：没装 OCR 依赖也不影响纯文本粘贴的使用
import os
import re

MAX_PDF_PAGES = 5      # 报告一般 1-2 页；限制页数，避免有人传 50 页 PDF 卡死
RENDER_DPI = 200       # 渲染分辨率：200dpi 下 10pt 小字也能识别，再高收益不大
MIN_TEXT_CHARS = 40    # PDF 文字层少于这么多字符，基本可以判定是扫描件/空页

_ENGINE = None         # RapidOCR 引擎缓存（首次加载模型约 1-2 秒）


class OcrUnavailable(RuntimeError):
    """OCR 相关依赖未安装时抛出，界面层捕获后给安装提示"""


def _import(name):
    try:
        return __import__(name, fromlist=["*"])
    except ImportError:
        return None


def available() -> dict:
    """各能力是否可用；界面用它决定提示文案"""
    return {"pypdf": _import("pypdf") is not None,
            "fitz": _import("fitz") is not None,
            "ocr": _import("rapidocr_onnxruntime") is not None}


def _engine():
    global _ENGINE
    if _ENGINE is None:
        mod = _import("rapidocr_onnxruntime")
        if mod is None:
            raise OcrUnavailable("未安装 OCR 依赖: pip install rapidocr-onnxruntime")
        _ENGINE = mod.RapidOCR()
    return _ENGINE


def pdf_text(path: str) -> str:
    """抽 PDF 的文字层；没有文字层返回空串"""
    mod = _import("pypdf")
    if mod is None:
        raise OcrUnavailable("未安装 PDF 依赖: pip install pypdf")
    reader = mod.PdfReader(path)
    pages = [p.extract_text() or "" for p in reader.pages[:MAX_PDF_PAGES]]
    return "\n".join(pages).strip()


def pdf_pages_to_images(path: str):
    """把扫描件 PDF 逐页渲染成 numpy 数组，喂给 OCR"""
    fitz = _import("fitz")
    if fitz is None:
        raise OcrUnavailable("未安装 PDF 渲染依赖: pip install pymupdf")
    import numpy as np
    doc = fitz.open(path)
    images = []
    for page in doc[:MAX_PDF_PAGES]:
        pix = page.get_pixmap(dpi=RENDER_DPI)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:                      # 带 alpha 的先压成 RGB，OCR 只要三通道
            arr = arr[:, :, :3]
        images.append(arr)
    doc.close()
    return images


def _group_rows(result, tol_ratio: float = 0.6):
    """把识别框按纵坐标聚成"视觉行"，行内按横坐标从左到右拼接。
    RapidOCR 是按文本块返回的，直接按顺序拼会把一行拆成"一个字一行"，
    解析层（每行=一个指标）就对不上了。"""
    items = []
    for line in result:
        box, text = line[0], line[1]
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((sum(ys) / len(ys), min(xs), max(ys) - min(ys), text))
    items.sort(key=lambda t: t[0])

    rows, cur, cur_y, cur_h = [], [], 0.0, 0.0
    for y, x, h, text in items:
        tol = max(cur_h, h) * tol_ratio if cur else 0.0
        if cur and abs(y - cur_y) <= tol:
            cur.append((x, text))
        else:
            if cur:
                rows.append(cur)
            cur, cur_y, cur_h = [(x, text)], y, h
        cur_h = max(cur_h, h)
    if cur:
        rows.append(cur)
    return [" ".join(t for _, t in sorted(row)) for row in rows]


# OCR 常把 ×10^9 认成 x10~9 / x10-9；不修的话解析层会把"10~9"当成参考范围，
# 导致整项判定错乱（比识别不出更危险）
_CARET = re.compile(r"[xX×]\s*10\s*[\^~～\-]\s*(\d+)")


def normalize(text: str) -> str:
    return _CARET.sub(r"×10^\1", text)


def ocr_image(image) -> str:
    """单张图（路径或 numpy 数组）→ 文本，先聚成视觉行再逐行输出"""
    result, _ = _engine()(image)
    if not result:
        return ""
    return normalize("\n".join(_group_rows(result)).strip())


def extract(path: str):
    """统一入口：返回（文本, 来源说明）。PDF 先试文字层，抽不到才走 OCR。"""
    if not path or not os.path.exists(path):
        raise FileNotFoundError(path)

    if path.lower().endswith(".pdf"):
        text = pdf_text(path)
        if len(text) >= MIN_TEXT_CHARS:      # 电子版报告：直接白拿，不 OCR
            return text, "PDF 文字层"
        pages = pdf_pages_to_images(path)
        if not pages:
            return "", "PDF 里没有可识别的页面"
        blocks = [ocr_image(p) for p in pages]
        return "\n".join(b for b in blocks if b).strip(), f"PDF 扫描件 OCR（{len(pages)} 页）"

    return ocr_image(path), "图片 OCR"
