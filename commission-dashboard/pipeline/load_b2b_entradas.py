"""Carrega as linhas AC="B2B" da aba Entradas (planilha Comissionamento B2C) pra
`fluency-finance.commission.b2b_entradas_snapshot` — base do modelo de comissão B2B
(Raphael, 2026-07-06): comissão = SUM(coluna L) × 6%, por vendedora (coluna AI),
quebrado por Contrato (coluna AD). Mês de corte = coluna F (Confirmação do pagamento).

⚠️ Modelo B2B (AC=B2B) é DIFERENTE do modelo b2b2c/Parceria (AC=B2B2C, 3%,
fluency-silver.hotmart.transactions) — fontes, taxas e filtros distintos. Não confundir.

Normalização de vendedora (decisões Raphael, 2026-07-06):
  - "Daiane Pencai" e "Daiane"           → "Daiane"
  - "Thayse Souza" e "Thayse"            → "Thayse"
  - "Luiz Felipe" e "Luis Felipe"        → "Luis Felipe"  (grafias da mesma pessoa)
  - "-" / vazio                          → "Sem carteira"
  - "#REF!" (fórmula quebrada na sheet)  → "Aguardando validação" (R$ 421.700,23 em
    2026-07-06 — excluído da comissão oficial até a Raphael corrigir a fórmula na
    planilha e reprocessar)

Uso:
    python load_b2b_entradas.py              # dry-run, mostra preview
    python load_b2b_entradas.py --commit      # grava no BQ (WRITE_TRUNCATE)
"""
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request

from google.cloud import bigquery

SHEET_ID = "1pTywGfEaXMewHf-h00Ozfpq2KB9XRQtefv8xs_iL-fs"
RANGE = "Entradas!A1:AI14132"
TABLE = "fluency-finance.commission.b2b_entradas_snapshot"

NORM_MAP = {
    "daiane pencai": "Daiane",
    "daiane": "Daiane",
    "thayse souza": "Thayse",
    "thayse": "Thayse",
    "luiz felipe": "Luis Felipe",
    "luis felipe": "Luis Felipe",
}


def get_token() -> str:
    return subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()


def fetch_entradas(token: str) -> list[list[str]]:
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{urllib.parse.quote(RANGE, safe='!:')}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    return data.get("values", [])


def bnum(s: str) -> float:
    if not s:
        return 0.0
    s = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(s: str):
    if not s:
        return None, None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s.strip())
    if not m:
        return None, None
    dd, mm, yyyy = m.groups()
    return f"{yyyy}-{mm}-{dd}", f"{yyyy}-{mm}"


def norm_vendedora(ai: str) -> str:
    ai = (ai or "").strip()
    if ai in ("", "-"):
        return "Sem carteira"
    if ai == "#REF!":
        return "Aguardando validação"
    return NORM_MAP.get(ai.lower(), ai)


def build_rows(values: list[list[str]]) -> list[dict]:
    rows = []
    for r in values[1:]:
        ac = r[28] if len(r) > 28 else ""
        if ac.strip() != "B2B":
            continue
        f = r[5] if len(r) > 5 else ""
        l = r[11] if len(r) > 11 else ""
        ad = (r[29] if len(r) > 29 else "").strip() or "(sem contrato)"
        ai = r[34] if len(r) > 34 else ""
        data_conf, mes = parse_date(f)
        rows.append({
            "data_confirmacao": data_conf,
            "mes": mes,
            "contrato": ad,
            "vendedora": norm_vendedora(ai),
            "vendedora_raw": ai,
            "valor": bnum(l),
        })
    return rows


def main():
    commit = "--commit" in sys.argv
    token = get_token()
    values = fetch_entradas(token)
    rows = build_rows(values)
    total = sum(r["valor"] for r in rows)
    print(f"{len(rows)} linhas AC=B2B extraídas da Entradas. Total L = {total:,.2f}")
    for r in rows[:5]:
        print(" ", r)
    if not commit:
        print("\nDry-run (sem --commit). Nada gravado no BQ.")
        return
    bq = bigquery.Client(project="fluency-finance")
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        schema=[
            bigquery.SchemaField("data_confirmacao", "DATE"),
            bigquery.SchemaField("mes", "STRING"),
            bigquery.SchemaField("contrato", "STRING"),
            bigquery.SchemaField("vendedora", "STRING"),
            bigquery.SchemaField("vendedora_raw", "STRING"),
            bigquery.SchemaField("valor", "NUMERIC"),
        ],
    )
    job = bq.load_table_from_json(rows, TABLE, job_config=job_config)
    job.result()
    print(f"✅ {len(rows)} linhas gravadas em {TABLE}")


if __name__ == "__main__":
    main()
