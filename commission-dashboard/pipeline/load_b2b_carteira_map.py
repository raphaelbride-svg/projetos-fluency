"""Carrega o de-para Tag Empresas → Carteira (vendedora B2B) da aba AUX da planilha
'Comissionamento B2C' [sic — mesma planilha usada por outras análises] pra
`fluency-finance.commission.b2b_carteira_map`.

Fonte: aba AUX, coluna U (Carteira) e coluna V (Tag Empresas) — de-para estático
(1 tag = 1 carteira, sem variação por mês, validado 2026-07-06: 302 tags, 0 conflitos).

O join com hotmart.transactions usa tracking_source (campo SRC, formato "[F]_Empresa"),
NÃO tracking_source_sck (esse é o e-mail de quem registrou a venda, não a empresa).

Uso:
    python load_b2b_carteira_map.py              # dry-run, mostra preview
    python load_b2b_carteira_map.py --commit      # grava no BQ (WRITE_TRUNCATE)
"""
import json
import subprocess
import sys
import urllib.parse
import urllib.request

from google.cloud import bigquery

SHEET_ID = "1pTywGfEaXMewHf-h00Ozfpq2KB9XRQtefv8xs_iL-fs"
RANGE = "AUX!A1:V13161"   # cobre até a coluna V (Tag Empresas); U = Carteira
TABLE = "fluency-finance.commission.b2b_carteira_map"

# Carteiras que não são vendedora real — normalizadas p/ "Sem carteira" no app, não aqui
# (mantemos o valor bruto na tabela; a normalização fica no /api/b2b pra não perder rastreabilidade)


def get_token() -> str:
    return subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()


def fetch_aux(token: str) -> list[list[str]]:
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{urllib.parse.quote(RANGE, safe='!:')}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    return data.get("values", [])


def build_rows(values: list[list[str]]) -> list[dict]:
    rows = []
    seen = {}
    for r in values[1:]:
        u = r[20] if len(r) > 20 else ""   # Carteira
        v = r[21] if len(r) > 21 else ""   # Tag Empresas
        if not v:
            continue
        v = v.strip()
        norm = v.lower()
        if norm in seen and seen[norm] != u:
            print(f"⚠️  conflito: tag '{v}' já visto com carteira '{seen[norm]}', agora '{u}' — mantendo o primeiro")
            continue
        if norm in seen:
            continue
        seen[norm] = u
        rows.append({"tag_empresa": v, "tag_empresa_norm": norm, "carteira": u})
    return rows


def main():
    commit = "--commit" in sys.argv
    token = get_token()
    values = fetch_aux(token)
    rows = build_rows(values)
    print(f"{len(rows)} tags únicos extraídos da AUX (coluna V → U).")
    for r in rows[:10]:
        print(" ", r)
    if not commit:
        print("\nDry-run (sem --commit). Nada gravado no BQ.")
        return
    bq = bigquery.Client(project="fluency-finance")
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        schema=[
            bigquery.SchemaField("tag_empresa", "STRING"),
            bigquery.SchemaField("tag_empresa_norm", "STRING"),
            bigquery.SchemaField("carteira", "STRING"),
        ],
    )
    job = bq.load_table_from_json(rows, TABLE, job_config=job_config)
    job.result()
    print(f"✅ {len(rows)} linhas gravadas em {TABLE}")


if __name__ == "__main__":
    main()
