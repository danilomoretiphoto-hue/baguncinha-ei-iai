"""Geração de relatórios de fechamento em Excel (.xlsx) com OpenPyXL."""

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.config import agora

VERDE = "10B981"
ESCURO = "0F172A"
CINZA = "1E293B"
AMARELO = "FEF3C7"
VERMELHO = "FEE2E2"
FORMATO_BRL = '"R$" #,##0.00'

_borda = Border(*(Side(style="thin", color="CBD5E1"),) * 4)
_fonte_header = Font(bold=True, color="FFFFFF")
_fill_header = PatternFill("solid", fgColor=VERDE)


def _formatar_data_hora(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def _aba_resumo(ws, resumo: Dict[str, Any], lancamentos: List[Dict[str, Any]]) -> None:
    ws.title = "Resumo do Dia"
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:C1")
    ws["A1"] = "Like Baguncinha — Fechamento de Caixa"
    ws["A1"].font = Font(bold=True, size=16, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=ESCURO)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    ws.merge_cells("A2:C2")
    try:
        data_fmt = datetime.fromisoformat(resumo["data_fechamento"]).strftime("%d/%m/%Y")
    except ValueError:
        data_fmt = resumo["data_fechamento"]
    ws["A2"] = f"Bebedouro - SP · Data: {data_fmt} · Gerado em {agora().strftime('%d/%m/%Y %H:%M')}"
    ws["A2"].font = Font(italic=True, color="475569")
    ws["A2"].alignment = Alignment(horizontal="center")

    for col, titulo in enumerate(["Indicador", "Valor", "Descrição"], start=1):
        c = ws.cell(row=4, column=col, value=titulo)
        c.font = _fonte_header
        c.fill = _fill_header
        c.border = _borda
        c.alignment = Alignment(horizontal="center")

    pendentes = sum(1 for l in lancamentos if l.get("status_validacao") == "PENDENTE_REVISAO")
    rejeitados = sum(1 for l in lancamentos if l.get("status_validacao") == "REJEITADO")

    linhas = [
        ("Total de Vendas Pagas", resumo["total_vendas_pago"], "Vendas à vista (PIX, dinheiro, cartão)", True),
        ("Total Fiado Gerado", resumo["total_fiado_gerado"], "Vendas marcadas no fiado (não entram no caixa)", True),
        ("Total Fiado Recebido", resumo["total_fiado_recebido"], "Pagamentos de fiado recebidos no dia", True),
        ("Total de Despesas", resumo["total_despesas"], "Contas e fornecedores (A_PAGAR)", True),
        ("Saldo Líquido do Dia", resumo["saldo_liquido_dia"], "Vendas pagas + fiado recebido − despesas", True),
        ("Quantidade de Transações", resumo["quantidade_transacoes"], "Lançamentos válidos (exclui rejeitados)", False),
        ("Pendentes de Revisão", pendentes, "Lançamentos aguardando conferência humana", False),
        ("Rejeitados", rejeitados, "Lançamentos descartados na conferência", False),
    ]
    for idx, (nome, valor, desc, moeda) in enumerate(linhas, start=5):
        ws.cell(row=idx, column=1, value=nome).font = Font(bold=True)
        cv = ws.cell(row=idx, column=2, value=valor)
        if moeda:
            cv.number_format = FORMATO_BRL
        ws.cell(row=idx, column=3, value=desc).font = Font(color="475569")
        for col in range(1, 4):
            ws.cell(row=idx, column=col).border = _borda
        if nome == "Saldo Líquido do Dia":
            for col in range(1, 4):
                ws.cell(row=idx, column=col).fill = PatternFill("solid", fgColor="D1FAE5")
            cv.font = Font(bold=True, color="065F46")

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 52


def _aba_detalhamento(ws, lancamentos: List[Dict[str, Any]], clientes: Dict[str, Dict[str, Any]]) -> None:
    cabecalho = [
        "ID", "Data/Hora", "Cliente", "Operação", "Tipo Pagamento", "Forma Pagamento",
        "Itens", "Valor Total", "Confiança IA", "Status", "Divergência", "Origem", "Observações",
    ]
    larguras = [22, 17, 28, 18, 18, 17, 60, 14, 13, 18, 12, 18, 60]
    ws.append(cabecalho)
    for col, largura in enumerate(larguras, start=1):
        cell = ws.cell(row=1, column=col)
        cell.font = _fonte_header
        cell.fill = _fill_header
        cell.border = _borda
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col)].width = largura

    for l in lancamentos:
        itens_txt = "; ".join(
            f"{i.get('quantidade', 1):g}x {i.get('descricao', '')} @ R$ {float(i.get('valor_unitario', 0)):.2f}"
            for i in l.get("itens", [])
        )
        ws.append([
            l.get("id"),
            _formatar_data_hora(l.get("data_hora", "")),
            clientes.get(l.get("cliente_id"), {}).get("nome", l.get("cliente_id")),
            l.get("tipo_operacao"),
            l.get("tipo_pagamento"),
            l.get("forma_pagamento"),
            itens_txt,
            float(l.get("valor_total") or 0),
            l.get("confianca_extracao"),
            l.get("status_validacao"),
            "SIM" if l.get("divergencia_calculo") else "NÃO",
            l.get("origem_dados"),
            l.get("observacoes", ""),
        ])
        row = ws.max_row
        ws.cell(row=row, column=8).number_format = FORMATO_BRL
        fill = None
        if l.get("status_validacao") == "REJEITADO":
            fill = PatternFill("solid", fgColor=VERMELHO)
        elif l.get("status_validacao") == "PENDENTE_REVISAO" or l.get("divergencia_calculo"):
            fill = PatternFill("solid", fgColor=AMARELO)
        for col in range(1, len(cabecalho) + 1):
            c = ws.cell(row=row, column=col)
            c.border = _borda
            c.alignment = Alignment(vertical="top", wrap_text=col in (7, 13))
            if fill:
                c.fill = fill

    if not lancamentos:
        ws.append(["Nenhum lançamento registrado nesta data."])

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cabecalho))}{max(ws.max_row, 1)}"


def gerar_xlsx_fechamento(
    resumo: Dict[str, Any],
    lancamentos: List[Dict[str, Any]],
    clientes: Dict[str, Dict[str, Any]],
) -> bytes:
    """Gera o arquivo Excel com as abas "Resumo do Dia" e "Detalhamento de Lançamentos"."""
    wb = Workbook()
    _aba_resumo(wb.active, resumo, lancamentos)
    _aba_detalhamento(wb.create_sheet("Detalhamento de Lançamentos"), lancamentos, clientes)
    wb.properties.title = f"Fechamento Like Baguncinha {resumo['data_fechamento']}"
    wb.properties.creator = "Agente Like Baguncinha"

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
