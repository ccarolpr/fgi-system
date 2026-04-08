from fastapi import FastAPI
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


@app.get("/", tags=["Status"])
def root():
    return {"status": "ok", "sistema": "FGI", "versao": "1.0.0"}
