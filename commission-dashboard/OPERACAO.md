# Commission Dashboard — Operação

> Estado em **04/06/2026**. Skill completa: `~/Documents/Fluency/.claude/skills/comissoes/SKILL.md`.

**Serviço:** Cloud Run `commission-dashboard` (us-central1) · projeto `fluency-finance`
**URL:** https://commission-dashboard-302941366897.us-central1.run.app
**Revisão atual:** `commission-dashboard-00035-nnt`

> O dash **abre no mês fechado mais recente** (último mês com `vlr_final_comissao > 0`), não no mês corrente vazio. `/api/months` retorna `{months, default}` e o `initMonths` seleciona o `default`. Hoje abre em **Maio/2026**; Junho só aparece selecionável (vazio até ser fechado).
**Deploy:** `gcloud run deploy commission-dashboard --source . --region us-central1`

---

## Fonte de dados (IMPORTANTE)

O app lê **duas tabelas nativas** em `fluency-finance.commission`:

| Tabela | Papel |
|---|---|
| `comissao_historica` | 1 linha por colaborador/mês: GBV, atingimento, multiplicador, comissão. **Fonte dos cards/ranking/trend.** |
| `hierarquia_comercial` | Dim de metas + hierarquia (mes/email/cargo/gestor/valor_meta). **Substitui a external `meta_vendedores`** em todo o caminho de exibição (RBAC, ranking, team-totals, tl-summary, trend, mom-compare, preview). |
| `parametros_folha` | DSR% por mês + reflexo (encargos) % — fonte do **Impacto em Folha**. Carregada da planilha oficial do FP&A `15W6Y…` aba **Comissao** via `build_parametros_folha.py`. |

### Impacto em Folha (modelo FP&A — planilha `15W6Y…` aba Comissao)
`DSR = comissão × dsr_rate(mês)` · `Reflexo(encargos) = (comissão+DSR) × 50%` · `Total = comissão + DSR + Reflexo`.
- **DSR% varia por mês** (Mai'26 = 20%, Jun'26 = 14,81%, …) — vem de `parametros_folha`, NÃO do calendário. Reflexo = 50% fixo.
- Aplica a **todos** uniformemente, **inclusive Fabio (PJ)** — a folha NÃO filtra ativos (todos com comissão>0 aparecem).
- Mai/2026 (valores oficiais após ajustes de 11/06/2026): comissão **278.002** · DSR **55.600** · Reflexo **166.801** · Total **500.404**.
- Atualizar quando o FP&A mexer nos DSR%: `python3 build_parametros_folha.py --commit`.

⚠️ A external **`meta_vendedores`** (Google Sheet `1DFaBtF…`) está **furada** (planilha errada, metas vazias, hierarquia desatualizada s/ Ana Pamplona). O app **NÃO** a usa mais para exibir — só sobra nas funções de refresh admin (`vw_comissao`/`_rebuild`), que continuam furadas.

---

## Como fechar um mês (fluxo correto)

Em `~/Documents/Fluency/finance/queries/comissoes/` (rodar com o python do venv: `~/projetos-fluency/commission-dashboard/venv/bin/python`):

```bash
python3 compute_<mes>.py          # apura pelos 5 modelos -> /tmp/<mes>.json
python3 load_historica.py         # PREVIEW (não grava)
python3 load_historica.py --commit    # grava comissao_historica (Abr+Mai)
python3 build_hierarquia.py --commit  # (re)cria a dim de metas/hierarquia
```

O dash acende sozinho (lê BQ ao vivo) — **não precisa redeploy** para mudança de dados.

❌ **NÃO usar** `/admin/refresh-current`, `/admin/close-previous`, `/admin/import-drive` para meses fechados pelo pipeline — eles reconstroem do `vw_comissao` (external furada + multiplicador genérico) e **sobrescrevem com número errado**.

---

## Crons (Cloud Scheduler, us-central1)

| Job | Quando | O que faz | Estado |
|---|---|---|---|
| `commission-refresh-diario` | diário 6h BRT | reconstrói **mês corrente** do `vw_comissao` | ENABLED (inócuo p/ meses fechados) |
| `commission-fecha-mes` | dia 8, 8h BRT | reconstrói **mês anterior** do `vw_comissao` | **⏸️ PAUSED em 04/06/2026** |

`commission-fecha-mes` foi pausado porque reconstruiria Maio (já fechado pelo pipeline) de volta para R$ 14.756.
**Só religar** (`gcloud scheduler jobs resume commission-fecha-mes --location=us-central1`) **depois** que o `vw_comissao`/external for repontado para a planilha "Comissionamento B2C" correta.

---

## Estado dos meses

| Mês | comissão | fonte | obs |
|---|---:|---|---|
| Abr/2026 | R$ 251.200 | pipeline (`load_historica`) | ok |
| Mai/2026 | R$ 263.910 | pipeline (`load_historica`) | ok |
| Jun/2026 | — | pendente | falta lançar metas + `compute_junho.py` |
