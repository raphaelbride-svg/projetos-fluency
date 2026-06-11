# Sync pendente p/ ~/Documents (bloqueado por macOS TCC em 11/06/2026)

O macOS revogou o acesso da shell/ferramentas à pasta `~/Documents` no meio da sessão (EPERM).
As mudanças abaixo precisam ser aplicadas QUANDO o acesso voltar
(Ajustes macOS → Privacidade e Segurança → Acesso Total ao Disco → habilitar o app de terminal/Claude).

## 1) Scripts-fonte em ~/Documents/Fluency/finance/queries/comissoes/
Estes JÁ têm `mult_deluchi` (editado antes do bloqueio) mas FALTA adicionar as TAXAS da Deluchi:

### compute_maio.py e compute_projecao.py
Adicionar a taxa própria da Ana Deluchi (canal Recuperação) e usá-la na base dela:
- `RATE_DELUCHI = {'a vista':0.08, 'parcelado':0.04, 'inteligente':0.0225}`
- No branch do vendedor: se `email == 'ana.deluchi@fluencyacademy.io'` → usar `RATE_DELUCHI` (não `RATE_ANALISTA`) p/ os componentes, e `mult_deluchi` p/ o multiplicador.
- A cópia COMPLETA e correta já está em `~/projetos-fluency/commission-dashboard/pipeline/compute_projecao.py` — basta copiar de lá quando o acesso voltar (`cp pipeline/compute_projecao.py ~/Documents/.../compute_projecao.py`).

## 2) SKILL.md (~/Documents/Fluency/.claude/skills/comissoes/SKILL.md)
Não foi atualizado hoje. O resumo COMPLETO das mudanças do dia está na **memória**:
`~/.claude/projects/-Users-fluencyacademy/memory/skill_commissions.md` (bloco "ATUALIZAÇÃO 11/06/2026").
Mesclar de lá. Tópicos: reapuração Maio R$282.272; projeção mês corrente (comissao_projecao + vw_comissao + Cloud Run job + schedulers); modelo Deluchi (Recuperação 8/4/2,25, mult até 1,3); mult alinhado aos PDFs; aba Rentabilidade por Modelo (month-aware + gráficos); e-mail finance@ (falta FINANCE_SMTP_PASS); colunas forma pgto/cliente; etc.

## 3) Pendências de negócio (não-código)
- **B2C junho:** metas em branco + novo TL/vendedores não estão na planilha. Atualizar a aba de junho da B2C (`1xEEO3JZyk0NzC9aQ9gF3xintxUZvlPGfDVlP30YeDFQ`) e reapurar.
- **`FINANCE_SMTP_PASS`** (App Password do finance@) → setar como secret no Cloud Run p/ ligar os e-mails de fechamento.
- **Deluchi:** confirmado mult até 1,3 + taxas 8/4/2,25 (Maio já corrigido no BQ = R$ 9.894,89).
