import os
os.environ.setdefault("TESSDATA_PREFIX", r"C:\Users\KWAY07\AppData\Local\tessdata")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.database import create_tables
from backend.routers import employees, atestados, reports

app = FastAPI(
    title="Sistema FGI — Fato Gerador Incerto",
    description="Automatização do cálculo de custos com atestados médicos não faturados ao cliente.",
    version="1.0.0",
)


@app.on_event("startup")
def startup():
    create_tables()


app.include_router(employees.router)
app.include_router(atestados.router)
app.include_router(reports.router)

app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse("frontend/index.html")


@app.get("/debug/ocr", tags=["Status"])
def debug_ocr():
    import subprocess
    tessdata = os.environ.get("TESSDATA_PREFIX", "NÃO DEFINIDO")
    try:
        from backend.services.ocr_service import _HAS_TESSERACT, _HAS_PDFPLUMBER
        has_t = _HAS_TESSERACT
        has_p = _HAS_PDFPLUMBER
    except Exception as e:
        has_t = str(e)
        has_p = str(e)
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        os.environ["TESSDATA_PREFIX"] = r"C:\Users\KWAY07\AppData\Local\tessdata"
        ver = str(pytesseract.get_tesseract_version())
        langs = pytesseract.get_languages()
    except Exception as e:
        ver = str(e)
        langs = []
    return {
        "TESSDATA_PREFIX": tessdata,
        "HAS_TESSERACT": has_t,
        "HAS_PDFPLUMBER": has_p,
        "tesseract_version": ver,
        "langs": langs,
    }
