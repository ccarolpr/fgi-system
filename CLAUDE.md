# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the API server
uvicorn backend.main:app --reload

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_calculator.py -v

# Run a single test by name
pytest tests/test_calculator.py::test_total_fgi_marco_2026 -v

# End-to-end integration test (requires server running on port 8000)
python scripts/seed_test.py
```

## Architecture

The system automates FGI (Fato Gerador Incerto) calculation — costs from employee sick leave (atestados) paid by the company but not billed to clients. The reference is `2026.3 - FG INCERTO CEINT.xlsx` with 34 employees; calculated totals must match centavo a centavo.

### Calculation pipeline

```
Atestados (confirmed) → consolidation.py (sum per employee/month) → fgi_calculator.py → preview_service.py → report_service.py (Excel)
```

1. **`backend/config.py`** — all financial constants (`HORAS_MES=220`, `HORAS_DIA=7.33`, `ENCARGOS=0.622`, `IMPOSTOS=0.0452`). Never change without formal approval.
2. **`fgi_calculator.py`** — pure function, no DB. Returns both rounded values (for display/Excel) and `_*_raw` keys for accurate total accumulation. Never sum rounded per-employee values for totals.
3. **`consolidation.py`** — aggregates multiple atestados per employee per month before calculation. FGI is always calculated on monthly totals, never per individual atestado.
4. **`hours_parser.py`** — converts `"01:30"` → `1.5` (minutes/60). Never treat as decimal `1.30`.
5. **`preview_service.py`** — consolidates confirmed atestados, runs FGI calculation, collects internal alerts (salary changes, high volume days). Alerts go here only, never to Excel.
6. **`report_service.py`** — rebuilds Excel from scratch using openpyxl (no template file needed). Output is identical to the reference spreadsheet.

### Key design rules

- **Alerts are internal only**: salary change alerts, volume alerts, new employee flags — visible in preview screen (`GET /reports/{ano}/{mes}/preview`), never written to Excel.
- **Employee identification**: CPF → automatic match; name only → return candidates for manual selection (never auto-match by name alone).
- **Period flow**: `aberto → previewed → gerado → fechado`. Excel generation requires period to be in `previewed` state.
- **Duplicate detection**: checked before confirming any atestado (CPF + data_inicio + dias). Alert is informational, does not block — user decides.
- **Salary audit**: every salary change in import is logged to `employee_audit` with `alerta_ativo=True` if variation exceeds thresholds in `config.py`.
- **Soft delete**: demitidos are marked `inativo`, never deleted. History is always preserved.
- **Rounding**: intermediaries use full float precision; `round(value, 2)` only at dict output. Totals accumulate `_*_raw` values, then round once.

### API endpoints summary

| Router | Prefix | Key endpoints |
|--------|--------|--------------|
| `employees.py` | `/employees` | CRUD + `POST /employees/import` (Excel upsert by CPF) |
| `atestados.py` | `/atestados` | `POST /upload` (OCR), `POST /manual`, `PATCH /{id}/confirmar`, `PATCH /{id}/vincular`, `POST /{id}/correcao` |
| `reports.py` | `/reports/{ano}/{mes}` | `GET /preview`, `POST /generate`, `GET /download`, `POST /fechar` |

### Database

SQLite (`fgi.db`), created automatically on first startup via `create_tables()` in `database.py`. Models: `Employee`, `EmployeeAudit`, `Atestado`, `AtestadoCorrecao`, `Period`.

### Validation target

```
March 2026, 34 employees (CEINT):
  Total FGI (col R):          R$ 7.173,76
  Total com encargos (col V): R$ 11.635,84
  Total final (col X):        R$ 12.161,78
```

`tests/test_calculator.py` validates all 34 employees centavo a centavo against these targets.
