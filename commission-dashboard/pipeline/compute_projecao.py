#!/usr/bin/env python3
"""Projecao do mes corrente (RITMO): GBV atual vs META PROPORCIONAL (meta/30 x dias_decorridos).
Reaproveita os modelos validados (calc_comissao). Roster: hierarquia_comercial do @mes;
se vazio, usa o mes mais recente com roster (ex.: junho vazio -> usa maio).
GBV: obt_conversions do @mes ate hoje (atribuicao dupla vendedor OR tracking_source_sck).
Escreve em commission.comissao_projecao (DELETE+load do @mes).

Uso: python3 compute_projecao.py [YYYY-MM] [--dias N] [--commit]
  sem mes  -> mes corrente (BRT)
  sem dias -> dia de hoje (BRT) se mes corrente, senao 30 (mes fechado)
"""
import sys, os, datetime, json, calendar
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # acha calc_comissao em qualquer cwd
from google.cloud import bigquery
from calc_comissao import (RATE_ANALISTA, RATE_TL_VANESSA, RATE_TL_TACYANA, OTE_ASSIST, OTE_TL_NOVO,
                           mult_analista, mult_assist, mult_tl_vanessa, mult_tl_tacyana, base_pct)

# ── Target sheet auto-sync ─────────────────────────────────────────────────────
UPLOAD_FOLDER_ID = "1gIiiFCXpvbdRjSYM-MmtcN5zA0Q6txJB"

_MONTH_PT_FULL = {
    1:"janeiro",2:"fevereiro",3:"março",4:"abril",5:"maio",6:"junho",
    7:"julho",8:"agosto",9:"setembro",10:"outubro",11:"novembro",12:"dezembro",
}
_TL_NAME_TO_EMAIL = {
    "matheus":              "matheus.batista@fluencyacademy.io",
    "matheus batista":      "matheus.batista@fluencyacademy.io",
    "matheus fernandes":    "matheus.fernandes@fluencyacademy.io",
    "tacyana bueno":        "tacyana.bueno@fluencyacademy.io",
    "tacyana":              "tacyana.bueno@fluencyacademy.io",
    "ana pamplona":         "anaclara.pamplona@fluencyacademy.io",
    "anaclara pamplona":    "anaclara.pamplona@fluencyacademy.io",
    "vanessa lopes":        "vanessa.lopes@fluencyacademy.io",
    "vanessa":              "vanessa.lopes@fluencyacademy.io",
    "fabio":                "fabio.dias@fluencyacademy.io",
    "fabio dias":           "fabio.dias@fluencyacademy.io",
}

def sync_target_sheet(mes_ym: str, bq_client: bigquery.Client) -> int:
    """
    Descobre o Target [Month] em UPLOAD_FOLDER_ID, lê a aba de presença e faz
    MERGEs no BQ para atualizar gestor e ote_fator em hierarquia_comercial.
    ote_fator = dias_trabalhados / dias_no_mes (proporcional para quem entrou no mês).
    Só age em mes >= 2026-06. Retorna nº de linhas com gestor atualizado.
    """
    if mes_ym < "2026-06":
        return 0
    try:
        import google.auth
        from googleapiclient.discovery import build
        creds, _ = google.auth.default(scopes=[
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/spreadsheets.readonly",
        ])
        drive_svc  = build("drive",  "v3", credentials=creds)
        sheets_svc = build("sheets", "v4", credentials=creds)

        year, month = int(mes_ym[:4]), int(mes_ym[5:7])
        month_name  = _MONTH_PT_FULL[month]
        result = drive_svc.files().list(
            q=(f"'{UPLOAD_FOLDER_ID}' in parents "
               f"and mimeType='application/vnd.google-apps.spreadsheet' "
               f"and name contains 'Target' and name contains '{year}'"),
            fields="files(id,name)", pageSize=20,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        file_id = next(
            (f["id"] for f in result.get("files", []) if month_name.lower() in f["name"].lower()),
            None
        )
        if not file_id:
            print(f"  sync_target_sheet: nenhuma sheet 'Target {month_name} - {year}' encontrada em upload/")
            return 0

        spreadsheet = sheets_svc.spreadsheets().get(spreadsheetId=file_id).execute()
        first_tab   = spreadsheet["sheets"][0]["properties"]["title"]
        rows = sheets_svc.spreadsheets().values().get(
            spreadsheetId=file_id, range=f"'{first_tab}'!A:I",
            valueRenderOption="FORMATTED_VALUE",
        ).execute().get("values", [])

        header_idx = next(
            (i for i, r in enumerate(rows) if r and str(r[0]).strip().lower() in ("company email","email","vendedor")),
            None
        )
        if header_idx is None:
            return 0

        mappings = []
        all_emails = []
        for row in rows[header_idx + 1:]:
            if not row or len(row) < 3: continue
            email = str(row[0]).strip().lower()
            if "@" not in email: continue
            all_emails.append(email)
            tl_name  = str(row[2]).strip().lower()
            tl_email = _TL_NAME_TO_EMAIL.get(tl_name)
            if tl_email:
                mappings.append({"email": email, "gestor": tl_email})

        if not mappings:
            return 0

        competencia = mes_ym + "-01"

        # ── MERGE 1: gestores ────────────────────────────────────────────────────
        rows_json = json.dumps(mappings)
        bq_client.query(f"""
            MERGE `fluency-finance.commission.hierarquia_comercial` T
            USING (
              SELECT LOWER(JSON_VALUE(raw, '$.email')) AS email,
                     JSON_VALUE(raw, '$.gestor')       AS gestor
              FROM UNNEST(JSON_QUERY_ARRAY(@rows)) AS raw
            ) S
            ON LOWER(T.email_vendedor) = S.email
               AND T.mes_venda = DATE('{competencia}')
            WHEN MATCHED THEN UPDATE SET T.gestor = S.gestor
        """, job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("rows","STRING",rows_json)]
        )).result()

        # ── ote_fator: consulta datas de admissão em people-analytics ────────────
        dias_no_mes  = calendar.monthrange(year, month)[1]
        mes_inicio   = datetime.date(year, month, 1)
        mes_fim      = datetime.date(year, month, dias_no_mes)

        people_bq = bigquery.Client(project="people-analytics-fluency")
        adm_rows  = people_bq.query(
            "SELECT LOWER(Email) AS email, Data_Admissao "
            "FROM `people-analytics-fluency.rh_staging.dim_nome` "
            "WHERE LOWER(Email) IN UNNEST(@emails)",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ArrayQueryParameter("emails","STRING",list(set(all_emails)))]
            ), location="southamerica-east1"
        ).result()
        admissao = {r["email"]: r["Data_Admissao"] for r in adm_rows}

        ote_rows = []
        newcomers_prop = []
        for email in all_emails:
            adm = admissao.get(email)
            if adm and adm >= mes_inicio:
                dias_trab = max(1, (mes_fim - adm).days + 1)
                fator     = round(min(1.0, dias_trab / dias_no_mes), 6)
                newcomers_prop.append(f"{email}({fator:.2f})")
            else:
                fator = 1.0
            ote_rows.append({"email": email, "ote_fator": fator})

        # ── MERGE 2: ote_fator ──────────────────────────────────────────────────
        ote_json = json.dumps(ote_rows)
        bq_client.query(f"""
            MERGE `fluency-finance.commission.hierarquia_comercial` T
            USING (
              SELECT LOWER(JSON_VALUE(raw, '$.email'))             AS email,
                     CAST(JSON_VALUE(raw, '$.ote_fator') AS FLOAT64) AS ote_fator
              FROM UNNEST(JSON_QUERY_ARRAY(@rows)) AS raw
            ) S
            ON LOWER(T.email_vendedor) = S.email
               AND T.mes_venda = DATE('{competencia}')
            WHEN MATCHED THEN UPDATE SET T.ote_fator = S.ote_fator
        """, job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("rows","STRING",ote_json)]
        )).result()

        prop_str = (", ".join(newcomers_prop)) or "(nenhum)"
        print(f"  sync_target_sheet: {len(mappings)} gestores | ote_fator proporcional: {prop_str}")
        return len(mappings)
    except Exception as e:
        print(f"  sync_target_sheet ERRO: {e}")
        return 0
# ──────────────────────────────────────────────────────────────────────────────

VANESSA='vanessa.lopes@fluencyacademy.io'; TACYANA='tacyana.bueno@fluencyacademy.io'
FABIO='fabio.dias@fluencyacademy.io'
DELUCHI='ana.deluchi@fluencyacademy.io'
RATE_DELUCHI={'a vista':0.08,'parcelado':0.04,'inteligente':0.0225}   # canal Recuperação (taxas próprias)
PROJ='fluency-finance.commission.comissao_projecao'
DIAS_BASE=30; OTE_FABIO=21600.0

def mult_coord(at):
    if at<0.80: return 0.5
    if at<0.95: return 0.8
    if at<1.20: return 1.0
    if at<1.30: return 1.2
    return 1.3

def mult_deluchi(at):   # Ana Deluchi (Recuperação) — tabela própria, vai até 1,3 (≥130%)
    if at is None: return 0
    if at<0.80: return 0.5
    if at<0.95: return 0.8
    if at<1.20: return 1.0
    if at<1.30: return 1.2
    return 1.3

# ---- args ----
COMMIT='--commit' in sys.argv
CLOSE='--close' in sys.argv   # snapshot do dia 8: grava o mês FECHADO em comissao_historica (dias=30)
HIST='fluency-finance.commission.comissao_historica'
mes=None; dias=None
for i,a in enumerate(sys.argv[1:],1):
    if a=='--dias': dias=int(sys.argv[i+1])
    elif len(a)>=7 and a[:2]=='20' and a[4]=='-': mes=a[:7]
now_brt=datetime.datetime.utcnow()-datetime.timedelta(hours=3)
if not mes:
    if CLOSE:   # dia 8 fecha o MÊS ANTERIOR
        py,pm = (now_brt.year-1,12) if now_brt.month==1 else (now_brt.year,now_brt.month-1)
        mes=f"{py:04d}-{pm:02d}"
    else:
        mes=f"{now_brt.year:04d}-{now_brt.month:02d}"
mes_date=mes+'-01'; y,m=map(int,mes.split('-'))
if CLOSE: dias=DIAS_BASE   # fechamento = mês inteiro (meta cheia, fator 1.0)
if dias is None:
    dias = now_brt.day if (now_brt.year,now_brt.month)==(y,m) else DIAS_BASE
fator=dias/DIAS_BASE
print(f"Projecao {mes} | dias={dias}/{DIAS_BASE} -> fator meta {fator:.4f}")

bq=bigquery.Client(project='fluency-finance')

# Sync de gestores e ote_fator deve rodar antes de carregar o roster (--commit)
if COMMIT:
    sync_target_sheet(mes, bq)

# ---- roster (fallback p/ mes mais recente com meta) ----
def load_roster(md):
    return list(bq.query(f"""
      SELECT LOWER(email_vendedor) email, LOWER(COALESCE(cargo,'')) cargo,
             LOWER(COALESCE(gestor,'')) gestor, CAST(COALESCE(valor_meta,0) AS FLOAT64) meta,
             CAST(COALESCE(ote_fator, 1.0) AS FLOAT64) ote_fator
      FROM `fluency-finance.commission.hierarquia_comercial`
      WHERE mes_venda=DATE('{md}') AND email_vendedor IS NOT NULL""").result())
roster=load_roster(mes_date); roster_src=mes_date
if not roster:
    latest=list(bq.query("SELECT MAX(mes_venda) m FROM `fluency-finance.commission.hierarquia_comercial` WHERE valor_meta>0").result())[0]['m']
    roster=load_roster(str(latest)); roster_src=str(latest)
    print(f"  roster {mes} vazio -> usando roster de {roster_src} (fallback)")

# ---- GBV do mes (split pos por modalidade + bruto/churn), atribuicao dupla ----
rows=list(bq.query(f"""
  WITH roster AS (
    SELECT LOWER(email_vendedor) email FROM `fluency-finance.commission.hierarquia_comercial`
    WHERE mes_venda=DATE('{roster_src}') AND LOWER(COALESCE(cargo,'')) IN ('vendedor','assistente')),
  obt AS (
    SELECT LOWER(vendedor) v, LOWER(tracking_source_sck) tsck, modality_payment,
           IF(is_churn,0,CAST(gbv AS NUMERIC)) gbv_pc, CAST(gbv AS NUMERIC) gbv_br,
           IF(is_churn,CAST(gbv AS NUMERIC),0) gbv_ch
    FROM `fluency-gold.conversion.obt_conversions`
    WHERE DATE_TRUNC(contract_created_at_brt_date,MONTH)=DATE('{mes_date}')
      AND modality_payment IN ('a vista','parcelado','inteligente'))
  SELECT r.email, o.modality_payment AS modal,
         CAST(SUM(o.gbv_pc) AS FLOAT64) gbv_pos,
         CAST(SUM(o.gbv_br) AS FLOAT64) gbv_bruto,
         CAST(SUM(o.gbv_ch) AS FLOAT64) churn
  FROM roster r JOIN obt o
    ON ((o.v IS NOT NULL AND o.v=r.email) OR (o.v IS NULL AND o.tsck LIKE CONCAT('%',r.email,'%')))
  GROUP BY 1,2""").result())
split={}; gross={}
for r in rows:
    e=r['email']; split.setdefault(e,{'a vista':0.0,'parcelado':0.0,'inteligente':0.0})
    split[e][r['modal']] += float(r['gbv_pos'])
    g=gross.setdefault(e,{'bruto':0.0,'churn':0.0}); g['bruto']+=float(r['gbv_bruto']); g['churn']+=float(r['churn'])
nina=float(list(bq.query(f"""SELECT CAST(SUM(IF(is_churn,0,gbv)) AS FLOAT64) g FROM `fluency-gold.conversion.obt_conversions`
  WHERE DATE_TRUNC(contract_created_at_brt_date,MONTH)=DATE('{mes_date}') AND LOWER(tracking_source_sck) LIKE '%.bot%'""").result())[0]['g'] or 0)

def comp(s,rt): return (s.get('a vista',0)*rt['a vista'], s.get('parcelado',0)*rt['parcelado'], s.get('inteligente',0)*rt['inteligente'])
def sp(e): return split.get(e,{'a vista':0.0,'parcelado':0.0,'inteligente':0.0})

# ---- colaboradores (vendedor/assistente) ----
out=[]   # cada item = dict pronto p/ load
teams={} # gestor -> agrega
for r in roster:
    e,cargo,gestor,meta,ote_fator = r['email'],r['cargo'],r['gestor'],float(r['meta']),float(r['ote_fator'])
    if cargo not in ('vendedor','assistente'): continue
    g=sp(e); tot=sum(g.values()); gr=gross.get(e,{}); bruto=gr.get('bruto',tot); churn=gr.get('churn',0.0)
    meta_prop=meta*fator; at=(tot/meta_prop) if meta_prop>0 else None
    if cargo=='assistente':
        mult=mult_assist(at); vlr=(at or 0)*OTE_ASSIST*ote_fator*mult; c_av=c_pa=c_in=0.0; base=vlr
    else:
        if e==DELUCHI:   # Recuperação: taxas próprias (8/4/2,25) + tabela própria (até 1,3)
            c_av,c_pa,c_in=comp(g,RATE_DELUCHI); base=c_av+c_pa+c_in; mult=mult_deluchi(at)
        else:
            c_av,c_pa,c_in=comp(g,RATE_ANALISTA); base=c_av+c_pa+c_in; mult=mult_analista(at)
        vlr=base*(mult or 0)
    out.append(dict(vendedor=e,gbv=bruto,churn=churn,gbv_liq=tot,c_av=c_av,c_pa=c_pa,c_in=c_in,
                    ating=at,mult=mult,total=base,vlr=vlr,meta_prop=meta_prop))
    t=teams.setdefault(gestor,{'split':{'a vista':0.0,'parcelado':0.0,'inteligente':0.0},'gbv':0.0,'meta':0.0})
    for k in t['split']: t['split'][k]+=g[k]
    t['gbv']+=tot; t['meta']+=meta

# ---- TLs ----
for r in roster:
    if 'team leader' not in r['cargo']: continue
    e=r['email']; t=teams.get(e)
    if not t: continue
    meta_prop=t['meta']*fator; at=(t['gbv']/meta_prop) if meta_prop>0 else 0
    ote_fator_tl = float(r.get('ote_fator', 1.0))
    if e==VANESSA:   c_av,c_pa,c_in=comp(t['split'],RATE_TL_VANESSA); base=c_av+c_pa+c_in; mult=mult_tl_vanessa(at); vlr=base*mult
    elif e==TACYANA: c_av,c_pa,c_in=comp(t['split'],RATE_TL_TACYANA); base=c_av+c_pa+c_in; mult=mult_tl_tacyana(at); vlr=base*mult
    else:            c_av=c_pa=c_in=0.0; mult=mult_assist(at); vlr=(at or 0)*OTE_TL_NOVO*ote_fator_tl*mult; base=vlr   # TL Novo (OTE proporcional)
    out.append(dict(vendedor=e,gbv=0.0,churn=0.0,gbv_liq=0.0,c_av=c_av,c_pa=c_pa,c_in=c_in,
                    ating=at,mult=mult,total=base,vlr=vlr,meta_prop=meta_prop))

# ---- Coordenador Fabio (canais; metas pro-rata; NINA=100%) ----
renov=teams.get(VANESSA,{}).get('gbv',0.0)
esteiras=sum(t['gbv'] for ge,t in teams.items() if ge!=VANESSA)
canais=[('Esteiras',0.70,7960000.0*fator,esteiras),('Renovacao',0.20,1600000.0*fator,renov),('Nina',0.10,nina,nina)]
fabio_vlr=0.0
for nm,peso,cm,cg in canais:
    cat=(cg/cm) if cm>0 else 0; mm=mult_coord(cat); ote=OTE_FABIO*peso; fabio_vlr+=ote*mm
out.append(dict(vendedor=FABIO,gbv=0.0,churn=0.0,gbv_liq=0.0,c_av=0.0,c_pa=0.0,c_in=0.0,
                ating=None,mult=None,total=fabio_vlr,vlr=fabio_vlr,meta_prop=None))

# ---- saida ----
tot_vlr=sum(o['vlr'] for o in out)
print(f"\n{'VENDEDOR':40}{'GBV_LIQ':>12}{'META_PROP':>12}{'AT':>7}{'MULT':>6}{'VLR':>11}")
for o in sorted(out,key=lambda x:-x['vlr'])[:45]:
    at='—' if o['ating'] is None else f"{o['ating']*100:.0f}%"; mu='—' if o['mult'] is None else f"{o['mult']:.1f}"
    print(f"{o['vendedor']:40}{o['gbv_liq']:>12,.0f}{(o['meta_prop'] or 0):>12,.0f}{at:>7}{mu:>6}{o['vlr']:>11,.2f}")
print(f"\n=== PROJECAO {mes} (dia {dias}/{DIAS_BASE}) ===\n{len(out)} linhas | comissao projetada TOTAL: R$ {tot_vlr:,.2f}")

if not COMMIT and not CLOSE:
    print("\n>>> PREVIEW. --commit grava na projecao | --close grava o FECHAMENTO em comissao_historica."); sys.exit(0)

ts=f"{mes_date}T00:00:00"; gerado=now_brt.strftime("%Y-%m-%dT%H:%M:%S")
base_cols=dict(contract_created_at_brt_timestamp=ts, transaction_confirmation_purchase_at_brt_timestamp=None)
def row_common(o):
    return dict(vendedor=o['vendedor'], **base_cols,
        gbv=round(o['gbv'],2), qtd_is_churn_transaction=0,
        gbv_apenas_churn_transaction=round(o['churn'],2), gbv_churn_descontado_transaction=round(o['gbv_liq'],2),
        comissao_inteligente=round(o['c_in'],4), comissao_parcelado=round(o['c_pa'],4), comissao_a_vista=round(o['c_av'],4),
        atingimento_meta=(None if o['ating'] is None else round(o['ating'],6)),
        multiplicador=o['mult'], total_comissao=round(o['total'],4), vlr_final_comissao=round(o['vlr'],2))

if CLOSE:
    # SNAPSHOT do dia 8: congela o mês fechado (meta cheia) em comissao_historica + limpa a projecao do mês
    load=[row_common(o) for o in out]
    bq.query(f"DELETE FROM `{HIST}` WHERE DATE_TRUNC(DATE(contract_created_at_brt_timestamp),MONTH)=DATE('{mes_date}')").result()
    jc=bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema=[bigquery.SchemaField(f.name,f.field_type) for f in bq.get_table(HIST).schema])
    bq.load_table_from_json(load,HIST,job_config=jc).result()
    bq.query(f"DELETE FROM `{PROJ}` WHERE DATE_TRUNC(DATE(contract_created_at_brt_timestamp),MONTH)=DATE('{mes_date}')").result()
    print(f"OK CLOSE: {len(load)} linhas FECHADAS em comissao_historica ({mes}); projecao do mês limpa.")
else:
    load=[dict(row_common(o), meta_proporcional=(None if o['meta_prop'] is None else round(o['meta_prop'],2)),
               dias_decorridos=dias, dias_base=DIAS_BASE, gerado_em=gerado) for o in out]
    bq.query(f"DELETE FROM `{PROJ}` WHERE DATE_TRUNC(DATE(contract_created_at_brt_timestamp),MONTH)=DATE('{mes_date}')").result()
    jc=bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema=[bigquery.SchemaField(f.name,f.field_type) for f in bq.get_table(PROJ).schema])
    bq.load_table_from_json(load,PROJ,job_config=jc).result()
    print(f"OK: {len(load)} linhas gravadas em comissao_projecao ({mes}).")
