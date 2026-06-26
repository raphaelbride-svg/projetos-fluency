#!/usr/bin/env python3
"""PDF de fechamento de comissoes - Maio 2026.
Usa venv do commission-dashboard. Execute com:
  venv/bin/python3 gerar_pdf_fechamento.py [YYYY-MM]
"""
import sys, warnings
warnings.filterwarnings("ignore")

MES = sys.argv[1] if len(sys.argv) > 1 else "2026-05"
MES_DATE = MES + "-01"
OUT = f"/Users/fluencyacademy/Desktop/fechamento_comissoes_{MES.replace('-','_')}.pdf"

MESES_PT = ["Janeiro","Fevereiro","Marco","Abril","Maio","Junho",
            "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
MES_LABEL = MESES_PT[int(MES.split("-")[1]) - 1] + "/" + MES.split("-")[0]

from google.cloud import bigquery
from fpdf import FPDF
from datetime import date

bq = bigquery.Client(project="fluency-finance")

NEWCOMERS = {"flavia.santos@fluencyacademy.io","daiana.felix@fluencyacademy.io","lorraine.santos@fluencyacademy.io"}
VANESSA   = "vanessa.lopes@fluencyacademy.io"
TACYANA   = "tacyana.bueno@fluencyacademy.io"
FABIO     = "fabio.dias@fluencyacademy.io"
OTE_ASSIST = 4000.0
OTE_TL_NOVO = 7000.0

def nome(email):
    parts = email.split("@")[0].split(".")
    return " ".join(p.capitalize() for p in parts[:2])

def brl(v):
    if v is None: return "-"
    return "R$ {:,.2f}".format(v).replace(",","X").replace(".",",").replace("X",".")

def pct(v):
    if v is None: return "-"
    return "{:.1f}%".format(v * 100)

def modelo(email, cargo):
    e = email.lower()
    c = (cargo or "").lower()
    if e == FABIO:   return "coord"
    if e == "ana.deluchi@fluencyacademy.io": return "deluchi"
    if e == VANESSA: return "tl_vanessa"
    if e == TACYANA: return "tl_tacyana"
    if "team leader" in c: return "tl_novo"
    if c == "assistente":  return "assistente"
    return "analista"

def corrige_ote(vlr, mod, ating, mult):
    if mod == "assistente": return (ating or 0) * OTE_ASSIST * (mult or 0)
    if mod == "tl_novo":    return (ating or 0) * OTE_TL_NOVO * (mult or 0)
    return vlr

print("Buscando dados do BQ...")

# 1. Comissao historica
hist = list(bq.query(f"""
  SELECT vendedor, gbv, gbv_churn_descontado_transaction AS gbv_liq,
         gbv_apenas_churn_transaction AS churn,
         atingimento_meta AS ating, multiplicador AS mult,
         vlr_final_comissao AS vlr
  FROM `fluency-finance.commission.comissao_historica`
  WHERE DATE_TRUNC(DATE(contract_created_at_brt_timestamp), MONTH) = DATE('{MES_DATE}')
""").result())

# 2. Hierarquia
hier = {r["email_vendedor"].lower(): r
        for r in bq.query(f"""
  SELECT LOWER(email_vendedor) email_vendedor, LOWER(COALESCE(cargo,'')) cargo,
         LOWER(COALESCE(gestor,'')) gestor, COALESCE(valor_meta,0) meta
  FROM `fluency-finance.commission.hierarquia_comercial`
  WHERE mes_venda = DATE('{MES_DATE}')
""").result()}

# 3. Extras aprovados por vendedor
extras_q = list(bq.query(f"""
  SELECT LOWER(vendedor) vendedor,
         SUM(CASE WHEN is_churn=0 OR is_churn IS NULL THEN CAST(gbv AS FLOAT64) ELSE 0 END) gbv_extra,
         COUNT(*) qtd
  FROM `fluency-finance.commission.extras_vendedores`
  WHERE competencia = DATE('{MES_DATE}')
    AND status_tl = 'aprovado' AND status_coord = 'aprovado'
  GROUP BY 1
""").result())
extras = {r["vendedor"]: {"gbv": float(r["gbv_extra"]), "qtd": int(r["qtd"])} for r in extras_q}

# 4. Signoff
sigs = {r["vendedor"].lower(): r["signed_at"]
        for r in bq.query(f"""
  SELECT LOWER(vendedor) vendedor, signed_at
  FROM `fluency-finance.commission.signoff_vendedores`
  WHERE competencia = DATE('{MES_DATE}')
""").result()}

# Monta linhas com correcao OTE
linhas = []
for r in hist:
    email = (r["vendedor"] or "").lower()
    h = hier.get(email, {})
    cargo = h.get("cargo", "") or ""
    gestor = h.get("gestor", "") or ""
    meta = float(h.get("meta", 0) or 0)
    mod = modelo(email, cargo)

    ating = float(r["ating"] or 0) if r["ating"] is not None else None
    mult  = float(r["mult"]  or 0) if r["mult"]  is not None else None
    gbv_liq = float(r["gbv_liq"] or 0)

    # newcomers: ating forcado
    if email in NEWCOMERS and ating is not None:
        ating = max(ating, 1.0)

    vlr = corrige_ote(float(r["vlr"] or 0), mod, ating, mult)

    ext = extras.get(email, {})
    gbv_extra = ext.get("gbv", 0.0)
    qtd_hp = ext.get("qtd", 0)

    signed = email in sigs

    linhas.append({
        "email":     email,
        "nome":      nome(email),
        "cargo":     cargo,
        "gestor":    gestor,
        "meta":      meta,
        "gbv_liq":   gbv_liq,
        "gbv_extra": gbv_extra,
        "ating":     ating,
        "mult":      mult,
        "vlr":       vlr,
        "qtd_hp":    qtd_hp,
        "signed":    signed,
        "mod":       mod,
    })

# Ordena: cargo > vlr desc
CARGO_ORD = {"coordenador":0,"gestor":0,"team leader":1,"tl_novo":1,"assistente":3,"vendedor":2,"deluchi":2}
def sort_key(l):
    c = l["cargo"]
    co = 9
    for k, v in CARGO_ORD.items():
        if k in c: co = v; break
    return (co, -l["vlr"])

linhas.sort(key=sort_key)

total_vlr = sum(l["vlr"] for l in linhas)
total_gbv = sum(l["gbv_liq"] + l["gbv_extra"] for l in linhas)
n_signed  = sum(1 for l in linhas if l["signed"])

print(f"  {len(linhas)} colaboradores | total comissao: {brl(total_vlr)} | aceites: {n_signed}/{len(linhas)}")

# ── PDF ──────────────────────────────────────────────────────────────────────
W = 277  # A4 landscape usable

class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 12)
        self.set_fill_color(30, 80, 160)
        self.set_text_color(255,255,255)
        self.set_xy(10, 8)
        self.cell(W, 10, f"Fechamento de Comissoes - {MES_LABEL}  |  fluency-finance", fill=True, ln=1)
        self.set_text_color(0,0,0)
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica","I",8)
        self.set_text_color(130,130,130)
        self.cell(W, 8, f"Gerado em {date.today().isoformat()}  -  Confidencial  -  pag. {self.page_no()}", align="C")

pdf = PDF(orientation="L", unit="mm", format="A4")
pdf.set_auto_page_break(auto=True, margin=14)
pdf.add_page()

# Resumo executivo
pdf.set_font("Helvetica","B",10)
pdf.set_fill_color(220,230,250)
pdf.set_text_color(20,50,130)
pdf.set_x(10)
pdf.cell(W, 7, "  Resumo do Fechamento", fill=True, ln=1)
pdf.set_text_color(0,0,0)
pdf.ln(1)

pdf.set_font("Helvetica","",9)
pdf.set_x(10)
pdf.cell(60, 5, f"Mes de competencia: {MES_LABEL}", ln=0)
pdf.cell(60, 5, f"Total colaboradores: {len(linhas)}", ln=0)
pdf.cell(70, 5, f"Total comissoes: {brl(total_vlr)}", ln=0)
pdf.cell(50, 5, f"Aceites: {n_signed}/{len(linhas)}", ln=1)
pdf.ln(3)

# Tabela principal
COLS  = ["Nome","Cargo","Gestor","Meta","GBV Liq.","HP","Atingimento","Mult","Comissao","Aceite"]
WIDTHS= [42,    22,     32,      22,    24,         10,  20,           14,    24,        17]

def th():
    pdf.set_font("Helvetica","B",8)
    pdf.set_fill_color(200,215,245)
    pdf.set_x(10)
    for c, w in zip(COLS, WIDTHS):
        pdf.cell(w, 6, c, border=1, fill=True, align="C")
    pdf.ln()

CARGO_LABELS = {
    "vendedor":"Vendedor","assistente":"Assistente","team leader":"TL",
    "coordenador":"Coord","gestor":"Coord",
}
def cargo_label(c):
    for k,v in CARGO_LABELS.items():
        if k in c: return v
    return c.capitalize()[:10]

th()
prev_cargo_group = None
row_n = 0
group_total = 0.0
group_label = ""

for l in linhas:
    cg = l["cargo"]
    # grupo visual
    grp = "TL" if "team leader" in cg else ("Assist." if cg=="assistente" else ("Coord" if "coord" in cg or "gestor" in cg else "Vendedor"))
    if grp != prev_cargo_group:
        if prev_cargo_group is not None and group_total > 0:
            pdf.set_font("Helvetica","B",8)
            pdf.set_fill_color(240,244,255)
            pdf.set_x(10)
            pdf.cell(sum(WIDTHS[:8]), 5, f"  Subtotal {group_label}", border=1, fill=True, align="L")
            pdf.cell(WIDTHS[8], 5, brl(group_total), border=1, fill=True, align="R")
            pdf.cell(WIDTHS[9], 5, "", border=1, fill=True)
            pdf.ln()
        prev_cargo_group = grp
        group_label = grp
        group_total = 0.0
        # header de grupo
        pdf.set_font("Helvetica","B",8)
        pdf.set_fill_color(30,80,160)
        pdf.set_text_color(255,255,255)
        pdf.set_x(10)
        pdf.cell(W, 5, f"  {grp}", fill=True, ln=1)
        pdf.set_text_color(0,0,0)
        th()

    fill = (row_n % 2 == 0)
    pdf.set_font("Helvetica","",8)
    pdf.set_fill_color(248,250,255)
    pdf.set_x(10)
    pdf.cell(WIDTHS[0], 5, l["nome"][:22],             border=1, fill=fill, align="L")
    pdf.cell(WIDTHS[1], 5, cargo_label(l["cargo"]),    border=1, fill=fill, align="C")
    gest_nome = nome(l["gestor"]) if l["gestor"] and "@" in l["gestor"] else (l["gestor"] or "-")[:14]
    pdf.cell(WIDTHS[2], 5, gest_nome[:18],             border=1, fill=fill, align="L")
    pdf.cell(WIDTHS[3], 5, brl(l["meta"]),             border=1, fill=fill, align="R")
    gbv_total = l["gbv_liq"] + l["gbv_extra"]
    pdf.cell(WIDTHS[4], 5, brl(gbv_total),             border=1, fill=fill, align="R")
    hp_str = str(l["qtd_hp"]) if l["qtd_hp"] else "-"
    pdf.cell(WIDTHS[5], 5, hp_str,                     border=1, fill=fill, align="C")
    pdf.cell(WIDTHS[6], 5, pct(l["ating"]) if l["ating"] is not None else "-",
                                                        border=1, fill=fill, align="C")
    mult_str = f"{l['mult']:.1f}x" if l["mult"] is not None else "-"
    pdf.cell(WIDTHS[7], 5, mult_str,                   border=1, fill=fill, align="C")
    pdf.set_font("Helvetica","B",8)
    pdf.cell(WIDTHS[8], 5, brl(l["vlr"]),              border=1, fill=fill, align="R")
    sign_str = "SIM" if l["signed"] else "NAO"
    pdf.set_font("Helvetica","",8)
    if l["signed"]:
        pdf.set_text_color(0,130,0)
    else:
        pdf.set_text_color(200,60,0)
    pdf.cell(WIDTHS[9], 5, sign_str,                   border=1, fill=fill, align="C")
    pdf.set_text_color(0,0,0)
    pdf.ln()

    group_total += l["vlr"]
    row_n += 1

# ultimo subtotal
if group_total > 0:
    pdf.set_font("Helvetica","B",8)
    pdf.set_fill_color(240,244,255)
    pdf.set_x(10)
    pdf.cell(sum(WIDTHS[:8]), 5, f"  Subtotal {group_label}", border=1, fill=True)
    pdf.cell(WIDTHS[8], 5, brl(group_total), border=1, fill=True, align="R")
    pdf.cell(WIDTHS[9], 5, "", border=1, fill=True)
    pdf.ln()

# Total geral
pdf.ln(2)
pdf.set_font("Helvetica","B",10)
pdf.set_fill_color(30,80,160)
pdf.set_text_color(255,255,255)
pdf.set_x(10)
pdf.cell(sum(WIDTHS[:8]), 7, "  TOTAL GERAL", fill=True, border=1)
pdf.cell(WIDTHS[8], 7, brl(total_vlr), fill=True, border=1, align="R")
pdf.cell(WIDTHS[9], 7, f"{n_signed}/{len(linhas)}", fill=True, border=1, align="C")
pdf.ln()
pdf.set_text_color(0,0,0)

pdf.output(OUT)
print(f"PDF gerado: {OUT}")
