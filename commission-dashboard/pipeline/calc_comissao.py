#!/usr/bin/env python3
"""Motor de cálculo de comissões B2C — fonte de verdade: planilha "Comissionamento B2C".
GBV por vendedor x forma de pagamento (pós-churn) vem de fluency-gold.conversion.obt_conversions.
Regras validadas 03/06/2026 contra a planilha 1xEEO3JZ (abas Antigos Vendedores, Novos Vendedores e TL, TL Vanessa, TL Tacyana).
"""
import json, csv

# ---- Regras (planilha Comissionamento B2C) ----
RATE_ANALISTA = {'a vista':0.10, 'parcelado':0.04, 'inteligente':0.013}      # Antigos Vendedores
RATE_TL_VANESSA = {'a vista':0.04, 'parcelado':0.015, 'inteligente':0.005}
RATE_TL_TACYANA = {'a vista':0.03, 'parcelado':0.01,  'inteligente':0.005}
OTE_ASSIST = 4000.0
OTE_TL_NOVO = 7000.0   # Novo TL I

def mult_analista(at):
    if at is None: return None
    if at < 0.75: return 0.3
    if at < 0.98: return 0.5
    if at < 1.20: return 1.0
    if at < 1.30: return 1.2
    if at < 1.50: return 1.3
    return 1.5

def mult_assist(at):   # tambem usado por Novo TL I e novos vendedores
    # Tabela oficial (PDF "2 - Comissionamento Assistentes Comerciais"): NAO existe degrau 1,2.
    # >=110% -> 1,3 (teto fixo do multiplicador); o % de atingimento continua escalando o valor
    # (130%, 140%... variam) na formula comissao = %ating x OTE x mult.
    if at is None: return 0.3
    if at < 0.70: return 0.3
    if at < 0.80: return 0.5
    if at < 0.90: return 0.7
    if at < 1.10: return 1.0
    return 1.3

def mult_tl_vanessa(at):
    if at is None: return None
    if at < 0.80: return 0.6
    if at < 0.95: return 0.8
    if at < 1.20: return 1.0
    return 1.2

def mult_tl_tacyana(at):
    if at is None: return None
    if at < 0.80: return 0.4
    if at < 1.00: return 0.6
    if at < 1.20: return 0.7
    return 1.0  # teto

def base_pct(gbv_by_type, rates):
    return sum(gbv_by_type.get(k,0)*rates[k] for k in rates)

def load_obt(mes):
    d = json.load(open('/tmp/obt_pivot.json'))
    out = {}
    for k,v in d.items():
        m, vend = k.split('|',1)
        if m==mes: out[vend]=v
    return out
