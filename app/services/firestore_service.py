"""Acesso ao Cloud Firestore e regras de negócio financeiras.

Observações sobre o plano Spark (gratuito):
- Somente metadados JSON são persistidos; nunca binários/base64 de mídia.
- Consultas usam apenas filtros de campo único (índices automáticos), evitando
  índices compostos; ordenações e filtros combinados são feitos em memória.
"""

import logging
import re
import secrets
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from google.cloud import firestore as gcf
from google.cloud.firestore_v1.base_query import FieldFilter

from app.config import TZ_BRASIL, agora_iso, hoje_str
from app.database import Collections, get_db
from app.services.gemini_service import is_cliente_balcao

logger = logging.getLogger(__name__)

CLIENTE_BALCAO_ID = "cliente-balcao"
CLIENTE_BALCAO_NOME = "Cliente Balcão"
DESPESAS_ID = "despesas-internas"
DESPESAS_NOME = "Like Baguncinha (Despesas Internas)"

VENDA = "VENDA"
PAGAMENTO_FIADO = "PAGAMENTO_FIADO"
DESPESA = "DESPESA"
PAGO = "PAGO"
FIADO_A_RECEBER = "FIADO_A_RECEBER"
A_PAGAR = "A_PAGAR"
REJEITADO = "REJEITADO"
APROVADO = "APROVADO"
PENDENTE_REVISAO = "PENDENTE_REVISAO"


class NotFoundError(Exception):
    """Recurso não encontrado."""


class RegraNegocioError(Exception):
    """Violação de regra de negócio."""


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def slugify(texto: str) -> str:
    txt = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^a-zA-Z0-9]+", "-", txt.lower()).strip("-")
    return txt[:60] or "cliente"


def normalizar_telefone(telefone: Optional[str]) -> str:
    digitos = re.sub(r"\D", "", telefone or "")
    if len(digitos) in (10, 11):
        digitos = "55" + digitos
    return digitos


def variantes_telefone(telefone: str) -> List[str]:
    """Gera variações (com/sem 55, com/sem nono dígito) para casar números do WhatsApp."""
    tel = normalizar_telefone(telefone)
    if not tel:
        return []
    variantes = {tel}
    if tel.startswith("55"):
        local = tel[2:]
        variantes.add(local)
        if len(local) == 11 and local[2] == "9":
            sem9 = local[:2] + local[3:]
            variantes.update({sem9, "55" + sem9})
        elif len(local) == 10:
            com9 = local[:2] + "9" + local[2:]
            variantes.update({com9, "55" + com9})
    return list(variantes)


def gerar_api_key() -> str:
    """API key aleatória hexadecimal de 32 caracteres."""
    return secrets.token_hex(16)


def _f(valor: Any) -> float:
    try:
        return round(float(valor or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def formatar_brl(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _doc(snapshot) -> Dict[str, Any]:
    dados = snapshot.to_dict() or {}
    dados["id"] = snapshot.id
    return dados


def _ativo(lanc: Dict[str, Any]) -> bool:
    return lanc.get("status_validacao") not in (REJEITADO, "CANCELADO")


def intervalo_dia(data_str: Optional[str] = None) -> Tuple[str, str]:
    dia = date.fromisoformat(data_str) if data_str else date.fromisoformat(hoje_str())
    inicio = datetime(dia.year, dia.month, dia.day, tzinfo=TZ_BRASIL)
    fim = inicio + timedelta(days=1)
    return inicio.isoformat(timespec="seconds"), fim.isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
def obter_cliente(cliente_id: str) -> Optional[Dict[str, Any]]:
    if not cliente_id:
        return None
    snap = get_db().collection(Collections.CLIENTES).document(cliente_id).get()
    return _doc(snap) if snap.exists else None


def listar_clientes() -> List[Dict[str, Any]]:
    clientes = [_doc(s) for s in get_db().collection(Collections.CLIENTES).stream()]
    return sorted(clientes, key=lambda c: (c.get("nome") or "").lower())


def mapa_clientes() -> Dict[str, Dict[str, Any]]:
    return {c["id"]: c for c in listar_clientes()}


def buscar_cliente_por_api_key(api_key: str) -> Optional[Dict[str, Any]]:
    if not api_key:
        return None
    query = (
        get_db().collection(Collections.CLIENTES)
        .where(filter=FieldFilter("api_key", "==", api_key))
        .limit(1)
    )
    for snap in query.stream():
        return _doc(snap)
    return None


def buscar_cliente_por_telefone(telefone: str) -> Optional[Dict[str, Any]]:
    col = get_db().collection(Collections.CLIENTES)
    for variante in variantes_telefone(telefone):
        for snap in col.where(filter=FieldFilter("telefone", "==", variante)).limit(1).stream():
            return _doc(snap)
    return None


def buscar_cliente_por_nome(nome: str) -> Optional[Dict[str, Any]]:
    slug = slugify(nome)
    direto = obter_cliente(slug)
    if direto:
        return direto
    for cliente in listar_clientes():
        if slugify(cliente.get("nome", "")) == slug:
            return cliente
    return None


def criar_cliente(
    nome: str,
    telefone: str = "",
    cpf_cnpj: Optional[str] = None,
    cliente_id: Optional[str] = None,
) -> Dict[str, Any]:
    col = get_db().collection(Collections.CLIENTES)
    tel = normalizar_telefone(telefone)

    if cliente_id:
        doc_id = slugify(cliente_id)
        if col.document(doc_id).get().exists:
            raise RegraNegocioError(f"Já existe um cliente com o ID '{doc_id}'.")
    else:
        base = slugify(nome)
        doc_id = base
        while col.document(doc_id).get().exists:
            doc_id = f"{base}-{uuid.uuid4().hex[:6]}"

    if tel and buscar_cliente_por_telefone(tel):
        raise RegraNegocioError(f"O telefone {tel} já está cadastrado para outro cliente.")

    dados = {
        "id": doc_id,
        "nome": " ".join(nome.split()),
        "telefone": tel,
        "cpf_cnpj": cpf_cnpj or None,
        "api_key": gerar_api_key(),
        "saldo_fiado_atual": 0.0,
        "criado_em": agora_iso(),
    }
    col.document(doc_id).set(dados)
    logger.info("Cliente criado: %s (%s)", dados["nome"], doc_id)
    return dados


def garantir_cliente_sistema(cliente_id: str, nome: str) -> Dict[str, Any]:
    existente = obter_cliente(cliente_id)
    if existente:
        return existente
    return criar_cliente(nome=nome, cliente_id=cliente_id)


def obter_ou_criar_cliente(nome: str, telefone: str = "") -> Dict[str, Any]:
    if is_cliente_balcao(nome):
        return garantir_cliente_sistema(CLIENTE_BALCAO_ID, CLIENTE_BALCAO_NOME)

    cliente = buscar_cliente_por_nome(nome)
    tel = normalizar_telefone(telefone)
    if cliente:
        if tel and not cliente.get("telefone") and not buscar_cliente_por_telefone(tel):
            get_db().collection(Collections.CLIENTES).document(cliente["id"]).update({"telefone": tel})
            cliente["telefone"] = tel
        return cliente

    if tel and buscar_cliente_por_telefone(tel):
        tel = ""
    return criar_cliente(nome=nome, telefone=tel)


# ---------------------------------------------------------------------------
# Lançamentos
# ---------------------------------------------------------------------------
def salvar_lancamento(dados: Dict[str, Any]) -> Dict[str, Any]:
    ref = get_db().collection(Collections.LANCAMENTOS).document()
    agora = agora_iso()
    raw_itens = dados.get("itens", []) or []
    itens_processados = [
        {
            "descricao": str(i["descricao"])[:200],
            "quantidade": float(i["quantidade"]),
            "valor_unitario": _f(i["valor_unitario"]),
            "valor_total_item": _f(float(i["quantidade"]) * float(i["valor_unitario"])),
        }
        for i in raw_itens
    ]
    if not itens_processados and dados.get("valor_total") is not None:
        vt = _f(dados.get("valor_total"))
        desc_padrao = "Fiado manual" if dados.get("tipo_pagamento") == FIADO_A_RECEBER else "Venda manual"
        itens_processados = [{"descricao": desc_padrao, "quantidade": 1.0, "valor_unitario": vt, "valor_total_item": vt}]

    total_calculado = _f(sum(i["valor_total_item"] for i in itens_processados)) if itens_processados else _f(dados.get("valor_total") or 0.0)

    documento = {
        "id": ref.id,
        "cliente_id": dados["cliente_id"],
        "data_hora": dados.get("data_hora") or agora,
        "tipo_operacao": dados["tipo_operacao"],
        "tipo_pagamento": dados["tipo_pagamento"],
        "forma_pagamento": dados["forma_pagamento"],
        "itens": itens_processados,
        "valor_total": total_calculado,
        "confianca_extracao": dados.get("confianca_extracao", "ALTO"),
        "status_validacao": dados.get("status_validacao", APROVADO),
        "divergencia_calculo": bool(dados.get("divergencia_calculo", False)),
        "origem_dados": dados.get("origem_dados", "TEXTO"),
        "transcricao_raw": str(dados.get("transcricao_raw", ""))[:8000],
        "observacoes": str(dados.get("observacoes", ""))[:2000],
        "criado_em": agora,
    }
    ref.set(documento)
    return documento


def obter_lancamento(lancamento_id: str) -> Optional[Dict[str, Any]]:
    snap = get_db().collection(Collections.LANCAMENTOS).document(lancamento_id).get()
    return _doc(snap) if snap.exists else None


def atualizar_lancamento(lancamento_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    ref = get_db().collection(Collections.LANCAMENTOS).document(lancamento_id)
    ref.update(updates)
    return _doc(ref.get())


def lancamentos_do_cliente(cliente_id: str) -> List[Dict[str, Any]]:
    query = get_db().collection(Collections.LANCAMENTOS).where(filter=FieldFilter("cliente_id", "==", cliente_id))
    lancs = [_doc(s) for s in query.stream()]
    return sorted(lancs, key=lambda l: l.get("data_hora", ""), reverse=True)


def listar_lancamentos(
    limit: int = 200,
    tipo_pagamento: Optional[str] = None,
    status_validacao: Optional[str] = None,
    busca: Optional[str] = None,
) -> List[Dict[str, Any]]:
    limite_busca = max(1, min(limit, 500))
    query = (
        get_db().collection(Collections.LANCAMENTOS)
        .order_by("data_hora", direction=gcf.Query.DESCENDING)
        .limit(limite_busca)
    )
    lancs = [_doc(s) for s in query.stream()]
    clientes = mapa_clientes()
    for l in lancs:
        l["cliente_nome"] = clientes.get(l.get("cliente_id"), {}).get("nome", l.get("cliente_id"))
    if tipo_pagamento:
        lancs = [l for l in lancs if l.get("tipo_pagamento") == tipo_pagamento]
    if status_validacao:
        lancs = [l for l in lancs if l.get("status_validacao") == status_validacao]
    if busca:
        termo = slugify(busca)
        lancs = [l for l in lancs if termo in slugify(l.get("cliente_nome") or "")]
    return lancs


def listar_pendentes() -> List[Dict[str, Any]]:
    query = get_db().collection(Collections.LANCAMENTOS).where(
        filter=FieldFilter("status_validacao", "==", PENDENTE_REVISAO)
    )
    lancs = [_doc(s) for s in query.stream()]
    clientes = mapa_clientes()
    for l in lancs:
        l["cliente_nome"] = clientes.get(l.get("cliente_id"), {}).get("nome", l.get("cliente_id"))
    return sorted(lancs, key=lambda l: l.get("data_hora", ""), reverse=True)


def lancamentos_por_periodo(inicio_iso: str, fim_iso: str) -> List[Dict[str, Any]]:
    query = (
        get_db().collection(Collections.LANCAMENTOS)
        .where(filter=FieldFilter("data_hora", ">=", inicio_iso))
        .where(filter=FieldFilter("data_hora", "<", fim_iso))
    )
    lancs = [_doc(s) for s in query.stream()]
    return sorted(lancs, key=lambda l: l.get("data_hora", ""))


# ---------------------------------------------------------------------------
# Fiado / saldo
# ---------------------------------------------------------------------------
def calcular_fiados_em_aberto(
    cliente_id: str, lancamentos: Optional[List[Dict[str, Any]]] = None
) -> Tuple[List[Dict[str, Any]], float]:
    """Aplica os pagamentos de fiado (FIFO) sobre os fiados mais antigos.

    Retorna (fiados_em_aberto_com_valor_em_aberto, saldo_fiado_atual).
    Fiados só deixam de estar em aberto mediante lançamento PAGAMENTO_FIADO.
    """
    lancs = lancamentos if lancamentos is not None else lancamentos_do_cliente(cliente_id)
    fiados = sorted(
        [l for l in lancs if _ativo(l) and l.get("tipo_pagamento") == FIADO_A_RECEBER
         and l.get("tipo_operacao") == VENDA],
        key=lambda l: l.get("data_hora", ""),
    )
    total_pago = _f(sum(_f(l.get("valor_total")) for l in lancs
                        if _ativo(l) and l.get("tipo_operacao") == PAGAMENTO_FIADO))
    total_fiado = _f(sum(_f(l.get("valor_total")) for l in fiados))

    restante = total_pago
    abertos: List[Dict[str, Any]] = []
    for fiado in fiados:
        valor = _f(fiado.get("valor_total"))
        if restante >= valor - 0.005:
            restante = _f(restante - valor)
            continue
        em_aberto = _f(valor - restante)
        restante = 0.0
        abertos.append({**fiado, "valor_em_aberto": em_aberto})

    saldo = _f(total_fiado - total_pago)
    return list(reversed(abertos)), saldo


def recalcular_saldo_cliente(cliente_id: str) -> float:
    _, saldo = calcular_fiados_em_aberto(cliente_id)
    ref = get_db().collection(Collections.CLIENTES).document(cliente_id)
    if ref.get().exists:
        ref.update({"saldo_fiado_atual": saldo})
    return saldo


def registrar_baixa_fiado(
    cliente_id: str, valor_pago: float, forma_pagamento: str, observacoes: Optional[str] = None
) -> Tuple[Dict[str, Any], float, float]:
    cliente = obter_cliente(cliente_id)
    if not cliente:
        raise NotFoundError(f"Cliente '{cliente_id}' não encontrado.")

    saldo_anterior = recalcular_saldo_cliente(cliente_id)
    if saldo_anterior <= 0:
        raise RegraNegocioError(f"O cliente {cliente['nome']} não possui saldo de fiado em aberto.")
    if valor_pago > saldo_anterior + 0.009:
        raise RegraNegocioError(
            f"Valor pago ({formatar_brl(valor_pago)}) maior que o saldo em aberto ({formatar_brl(saldo_anterior)})."
        )

    lancamento = salvar_lancamento({
        "cliente_id": cliente_id,
        "tipo_operacao": PAGAMENTO_FIADO,
        "tipo_pagamento": PAGO,
        "forma_pagamento": forma_pagamento,
        "itens": [{"descricao": "Pagamento de fiado (baixa manual)", "quantidade": 1.0, "valor_unitario": valor_pago}],
        "confianca_extracao": "ALTO",
        "status_validacao": APROVADO,
        "divergencia_calculo": False,
        "origem_dados": "TEXTO",
        "transcricao_raw": f"Baixa manual de fiado via painel admin: {formatar_brl(valor_pago)} em {forma_pagamento}.",
        "observacoes": observacoes or "",
    })
    saldo_atual = recalcular_saldo_cliente(cliente_id)
    return lancamento, saldo_anterior, saldo_atual


# ---------------------------------------------------------------------------
# Pipeline de persistência de extrações da IA
# ---------------------------------------------------------------------------
def registrar_lancamento_extraido(
    normalizado: Dict[str, Any],
    origem_dados: str,
    cliente_id: Optional[str] = None,
    telefone_remetente: Optional[str] = None,
    nome_contato: Optional[str] = None,
    arquivo_ref: Optional[str] = None,
    from_me: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Resolve o cliente, persiste o lançamento e ajusta o saldo de fiado.

    Prioridade de associação de cliente:
    1. `cliente_id` explícito;
    2. DESPESA -> cliente interno de despesas (fornecedor vai para observações);
    3. Nome citado no conteúdo (diferente de "Cliente Balcão");
    4. Telefone do remetente do WhatsApp (cadastra automaticamente se desconhecido);
    5. "Cliente Balcão".
    """
    observacoes: List[str] = [normalizado.get("observacoes", "")] if normalizado.get("observacoes") else []
    nome_extraido = normalizado.get("cliente_nome") or CLIENTE_BALCAO_NOME
    telefone_extraido = normalizado.get("cliente_telefone") or ""

    if cliente_id:
        cliente = obter_cliente(cliente_id)
        if not cliente:
            raise NotFoundError(f"Cliente '{cliente_id}' não encontrado.")
    elif normalizado.get("tipo_operacao") == DESPESA:
        cliente = garantir_cliente_sistema(DESPESAS_ID, DESPESAS_NOME)
        if not is_cliente_balcao(nome_extraido):
            observacoes.insert(0, f"Fornecedor/credor: {nome_extraido}")
    elif not is_cliente_balcao(nome_extraido):
        cliente = obter_ou_criar_cliente(nome_extraido, telefone_extraido)
    elif telefone_remetente and not from_me:
        cliente = buscar_cliente_por_telefone(telefone_remetente)
        if not cliente:
            nome_novo = (nome_contato or "").strip() or f"Contato WhatsApp {normalizar_telefone(telefone_remetente)}"
            cliente = criar_cliente(nome=nome_novo, telefone=telefone_remetente)
            observacoes.append("Cliente cadastrado automaticamente pelo telefone do WhatsApp.")
    else:
        cliente = garantir_cliente_sistema(CLIENTE_BALCAO_ID, CLIENTE_BALCAO_NOME)

    if arquivo_ref:
        observacoes.append(f"Arquivo de origem (não armazenado): {arquivo_ref[:300]}")

    lancamento = salvar_lancamento({
        "cliente_id": cliente["id"],
        "tipo_operacao": normalizado["tipo_operacao"],
        "tipo_pagamento": normalizado["tipo_pagamento"],
        "forma_pagamento": normalizado["forma_pagamento"],
        "itens": normalizado["itens"],
        "confianca_extracao": normalizado["confianca_extracao"],
        "status_validacao": normalizado["status_validacao"],
        "divergencia_calculo": normalizado["divergencia_calculo"],
        "origem_dados": origem_dados,
        "transcricao_raw": normalizado.get("transcricao_raw", ""),
        "observacoes": " | ".join(o for o in observacoes if o),
    })

    if lancamento["tipo_pagamento"] == FIADO_A_RECEBER or lancamento["tipo_operacao"] == PAGAMENTO_FIADO:
        cliente["saldo_fiado_atual"] = recalcular_saldo_cliente(cliente["id"])

    lancamento["cliente_nome"] = cliente.get("nome")
    return lancamento, cliente


def validar_lancamento(
    lancamento_id: str,
    status_validacao: str,
    itens: Optional[List[Dict[str, Any]]] = None,
    tipo_operacao: Optional[str] = None,
    tipo_pagamento: Optional[str] = None,
    forma_pagamento: Optional[str] = None,
    cliente_id: Optional[str] = None,
    observacoes: Optional[str] = None,
) -> Dict[str, Any]:
    from app.models.lancamento import coerencia_tipos

    atual = obter_lancamento(lancamento_id)
    if not atual:
        raise NotFoundError(f"Lançamento '{lancamento_id}' não encontrado.")

    updates: Dict[str, Any] = {"status_validacao": status_validacao}
    correcoes: List[str] = []

    if itens is not None:
        novos_itens = [
            {
                "descricao": str(i["descricao"])[:200],
                "quantidade": float(i["quantidade"]),
                "valor_unitario": _f(i["valor_unitario"]),
                "valor_total_item": _f(float(i["quantidade"]) * float(i["valor_unitario"])),
            }
            for i in itens
        ]
        updates["itens"] = novos_itens
        updates["valor_total"] = _f(sum(i["valor_total_item"] for i in novos_itens))
        updates["divergencia_calculo"] = False
        correcoes.append(
            f"Itens corrigidos manualmente (total {formatar_brl(_f(atual.get('valor_total')))} → "
            f"{formatar_brl(updates['valor_total'])})"
        )

    if tipo_operacao or tipo_pagamento or forma_pagamento:
        op, tp, forma, _ = coerencia_tipos(
            tipo_operacao or atual.get("tipo_operacao", VENDA),
            tipo_pagamento or atual.get("tipo_pagamento", PAGO),
            forma_pagamento or atual.get("forma_pagamento", "DINHEIRO"),
        )
        updates.update({"tipo_operacao": op.value, "tipo_pagamento": tp.value, "forma_pagamento": forma.value})
        if (op.value, tp.value, forma.value) != (
            atual.get("tipo_operacao"), atual.get("tipo_pagamento"), atual.get("forma_pagamento")
        ):
            correcoes.append(f"Classificação ajustada para {op.value}/{tp.value}/{forma.value}")

    cliente_antigo = atual.get("cliente_id")
    if cliente_id and cliente_id != cliente_antigo:
        if not obter_cliente(cliente_id):
            raise NotFoundError(f"Cliente '{cliente_id}' não encontrado.")
        updates["cliente_id"] = cliente_id
        correcoes.append(f"Cliente alterado de '{cliente_antigo}' para '{cliente_id}'")

    base_obs = observacoes if observacoes is not None else atual.get("observacoes", "")
    nota = f"[Revisão humana {agora_iso()}: {status_validacao}" + (f" — {'; '.join(correcoes)}" if correcoes else "") + "]"
    updates["observacoes"] = " | ".join(p for p in [base_obs, nota] if p)[:2000]

    atualizado = atualizar_lancamento(lancamento_id, updates)

    for cid in {cliente_antigo, atualizado.get("cliente_id")}:
        if cid:
            recalcular_saldo_cliente(cid)

    cliente = obter_cliente(atualizado.get("cliente_id", ""))
    atualizado["cliente_nome"] = cliente.get("nome") if cliente else None
    return atualizado


# ---------------------------------------------------------------------------
# Fechamento e dashboard
# ---------------------------------------------------------------------------
def calcular_fechamento(data_str: Optional[str] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    data_ref = data_str or hoje_str()
    inicio, fim = intervalo_dia(data_ref)
    lancs = lancamentos_por_periodo(inicio, fim)
    ativos = [l for l in lancs if _ativo(l)]

    def soma(filtro) -> float:
        return _f(sum(_f(l.get("valor_total")) for l in ativos if filtro(l)))

    total_vendas_pago = soma(lambda l: l.get("tipo_operacao") == VENDA and l.get("tipo_pagamento") == PAGO)
    total_fiado_gerado = soma(lambda l: l.get("tipo_pagamento") == FIADO_A_RECEBER)
    total_fiado_recebido = soma(lambda l: l.get("tipo_operacao") == PAGAMENTO_FIADO)
    total_despesas = soma(lambda l: l.get("tipo_operacao") == DESPESA)

    resumo = {
        "data_fechamento": data_ref,
        "total_vendas_pago": total_vendas_pago,
        "total_fiado_gerado": total_fiado_gerado,
        "total_fiado_recebido": total_fiado_recebido,
        "total_despesas": total_despesas,
        "saldo_liquido_dia": _f(total_vendas_pago + total_fiado_recebido - total_despesas),
        "quantidade_transacoes": len(ativos),
    }
    return resumo, lancs


def salvar_fechamento(data_str: Optional[str] = None) -> Dict[str, Any]:
    resumo, _ = calcular_fechamento(data_str)
    col = get_db().collection(Collections.FECHAMENTOS)
    existentes = list(
        col.where(filter=FieldFilter("data_fechamento", "==", resumo["data_fechamento"])).limit(1).stream()
    )
    if existentes:
        ref = existentes[0].reference
        ref.update({**resumo, "criado_em": agora_iso()})
    else:
        ref = col.document()
        ref.set({"id": ref.id, **resumo, "criado_em": agora_iso()})
    return _doc(ref.get())


def dashboard_kpis() -> Dict[str, Any]:
    resumo, _ = calcular_fechamento(hoje_str())
    clientes = listar_clientes()
    total_a_receber = _f(sum(max(_f(c.get("saldo_fiado_atual")), 0.0) for c in clientes))
    pendentes = get_db().collection(Collections.LANCAMENTOS).where(
        filter=FieldFilter("status_validacao", "==", PENDENTE_REVISAO)
    ).stream()
    return {
        "data_referencia": resumo["data_fechamento"],
        "total_vendido_hoje": resumo["total_vendas_pago"],
        "total_fiado_gerado_hoje": resumo["total_fiado_gerado"],
        "total_fiado_a_receber": total_a_receber,
        "total_recebido_fiado_hoje": resumo["total_fiado_recebido"],
        "total_despesas_hoje": resumo["total_despesas"],
        "saldo_liquido_hoje": resumo["saldo_liquido_dia"],
        "pendencias_conferencia": sum(1 for _ in pendentes),
        "quantidade_transacoes_hoje": resumo["quantidade_transacoes"],
        "quantidade_clientes": len([c for c in clientes if c["id"] not in (CLIENTE_BALCAO_ID, DESPESAS_ID)]),
    }


# ---------------------------------------------------------------------------
# Cobrança
# ---------------------------------------------------------------------------
def gerar_mensagem_cobranca(cliente_id: str) -> Dict[str, Any]:
    cliente = obter_cliente(cliente_id)
    if not cliente:
        raise NotFoundError(f"Cliente '{cliente_id}' não encontrado.")
    abertos, saldo = calcular_fiados_em_aberto(cliente_id)
    get_db().collection(Collections.CLIENTES).document(cliente_id).update({"saldo_fiado_atual": saldo})

    nome = cliente.get("nome", "")
    linhas = [f"Olá {nome}, seu saldo no Like Baguncinha é {formatar_brl(saldo)}."]
    if abertos:
        linhas.append("Seguem os lançamentos em aberto:")
        linhas.append("")
        for l in sorted(abertos, key=lambda x: x.get("data_hora", "")):
            try:
                data_fmt = datetime.fromisoformat(l.get("data_hora", "")).strftime("%d/%m")
            except ValueError:
                data_fmt = "--/--"
            itens = ", ".join(
                f"{i.get('quantidade', 1):g}x {i.get('descricao', '')}" for i in l.get("itens", [])
            ) or "Compra"
            linhas.append(f"• {data_fmt} — {itens}: {formatar_brl(l['valor_em_aberto'])}")
        linhas.append("")
        linhas.append("Pode pagar via PIX ou direto no balcão. Qualquer dúvida estamos à disposição!")
    else:
        linhas.append("Você não possui lançamentos de fiado em aberto. Obrigado pela preferência!")
    linhas.append("Like Baguncinha — Bebedouro/SP 💚")
    mensagem = "\n".join(linhas)

    telefone = cliente.get("telefone") or ""
    return {
        "cliente_id": cliente_id,
        "nome": nome,
        "telefone": telefone,
        "saldo_fiado_atual": saldo,
        "quantidade_lancamentos_em_aberto": len(abertos),
        "mensagem": mensagem,
        "whatsapp_link": f"https://wa.me/{telefone}?text={quote(mensagem)}" if telefone else None,
    }


# ---------------------------------------------------------------------------
# Logs de webhook
# ---------------------------------------------------------------------------
def sanitizar_payload(obj: Any, max_len: int = 1500, profundidade: int = 0) -> Any:
    """Remove conteúdos pesados (base64, binários) antes de gravar no Firestore."""
    if profundidade > 8:
        return "[estrutura truncada]"
    if isinstance(obj, dict):
        return {
            (str(k) or "_vazio")[:100]: sanitizar_payload(v, max_len, profundidade + 1)
            for k, v in list(obj.items())[:100]
        }
    if isinstance(obj, (list, tuple)):
        return [sanitizar_payload(v, max_len, profundidade + 1) for v in list(obj)[:50]]
    if isinstance(obj, (bytes, bytearray)):
        return f"[binário omitido: {len(obj)} bytes]"
    if isinstance(obj, str) and len(obj) > max_len:
        return f"[conteúdo omitido: {len(obj)} caracteres]"
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    return str(obj)[:max_len]


def registrar_log_webhook(
    payload: Any, status: str, mensagem_erro: Optional[str] = None, origem: str = "WHATSAPP"
) -> Dict[str, Any]:
    ref = get_db().collection(Collections.LOGS_WEBHOOK).document()
    payload_limpo = sanitizar_payload(payload if isinstance(payload, dict) else {"raw": payload})
    documento = {
        "id": ref.id,
        "origem": origem,
        "payload_recebido": payload_limpo,
        "status_processamento": status,
        "mensagem_erro": (mensagem_erro or None) and str(mensagem_erro)[:2000],
        "criado_em": agora_iso(),
    }
    ref.set(documento)
    return documento


# ---------------------------------------------------------------------------
# Operações complementares para rotas /api
# ---------------------------------------------------------------------------
def excluir_lancamento(
    lancamento_id: str, permanente: bool = False, motivo: Optional[str] = None
) -> Dict[str, Any]:
    """Exclui ou cancela um lançamento com estorno automático de saldos."""
    atual = obter_lancamento(lancamento_id)
    if not atual:
        raise NotFoundError(f"Lançamento '{lancamento_id}' não encontrado.")

    cliente_id = atual.get("cliente_id")

    if permanente:
        get_db().collection(Collections.LANCAMENTOS).document(lancamento_id).delete()
        saldo_atual = recalcular_saldo_cliente(cliente_id) if cliente_id else 0.0
        return {
            "id": lancamento_id,
            "status": "REMOVIDO",
            "permanente": True,
            "mensagem": f"Lançamento '{lancamento_id}' excluído permanentemente do Firestore.",
            "cliente_id": cliente_id,
            "saldo_fiado_atual": saldo_atual,
        }
    else:
        agora = agora_iso()
        nota_cancelamento = f"[Cancelado em {agora}" + (f": {motivo}" if motivo else "") + "]"
        obs_atual = atual.get("observacoes", "")
        nova_obs = f"{obs_atual} | {nota_cancelamento}".strip(" | ")[:2000]

        updates = {
            "status_validacao": "CANCELADO",
            "observacoes": nova_obs,
            "cancelado_em": agora,
        }
        atualizado = atualizar_lancamento(lancamento_id, updates)
        saldo_atual = recalcular_saldo_cliente(cliente_id) if cliente_id else 0.0
        cliente = obter_cliente(cliente_id) if cliente_id else None
        atualizado["cliente_nome"] = cliente.get("nome") if cliente else None
        atualizado["saldo_fiado_atual"] = saldo_atual
        return atualizado


def criar_lancamento_manual(
    cliente: Optional[str] = None,
    cliente_id: Optional[str] = None,
    itens: Optional[List[Dict[str, Any]]] = None,
    valor_total: Optional[float] = None,
    tipo: Optional[str] = None,
    forma_pagamento: Optional[str] = None,
    status: Optional[str] = None,
    confianca: Optional[str] = None,
    observacoes: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Cria manualmente um lançamento (venda ou fiado), atualizando saldo de fiado."""
    # 1. Resolução do cliente
    if cliente_id:
        c = obter_cliente(cliente_id)
        if not c:
            raise NotFoundError(f"Cliente '{cliente_id}' não encontrado.")
    elif cliente:
        c = obter_ou_criar_cliente(cliente)
        cliente_id = c["id"]
    else:
        c = garantir_cliente_sistema(CLIENTE_BALCAO_ID, CLIENTE_BALCAO_NOME)
        cliente_id = CLIENTE_BALCAO_ID

    # 2. Resolução do tipo e forma de pagamento
    tipo_str = (tipo or "VENDA").upper()
    forma_str = (forma_pagamento or "DINHEIRO").upper()
    if forma_str == "CARTAO":
        forma_str = "CARTAO_CREDITO"

    if tipo_str == "FIADO" or forma_str == "FIADO":
        tipo_op = VENDA
        tipo_pag = FIADO_A_RECEBER
        forma_pag = "FIADO"
    else:
        tipo_op = VENDA
        tipo_pag = PAGO
        forma_pag = forma_str

    # 3. Status de validação
    status_str = (status or APROVADO).upper()
    if status_str in ("PENDENTE_CONFERENCIA", "PENDENTE_REVISAO"):
        status_val = PENDENTE_REVISAO
    elif status_str in (APROVADO, "CANCELADO", REJEITADO):
        status_val = status_str
    else:
        status_val = APROVADO

    # 4. Itens e valor
    itens_formatados: List[Dict[str, Any]] = []
    if itens:
        for it in itens:
            q = float(it.get("quantidade", 1.0))
            u = _f(it.get("valor_unitario", 0.0))
            itens_formatados.append({
                "descricao": str(it.get("descricao", "Item"))[:200],
                "quantidade": q,
                "valor_unitario": u,
                "valor_total_item": _f(q * u),
            })
        vt_calc = _f(sum(i["valor_total_item"] for i in itens_formatados))
    elif valor_total is not None and valor_total > 0:
        vt_calc = _f(valor_total)
        desc = "Fiado manual" if tipo_pag == FIADO_A_RECEBER else "Venda manual"
        itens_formatados = [{"descricao": desc, "quantidade": 1.0, "valor_unitario": vt_calc, "valor_total_item": vt_calc}]
    else:
        vt_calc = 0.0

    lanc = salvar_lancamento({
        "cliente_id": cliente_id,
        "tipo_operacao": tipo_op,
        "tipo_pagamento": tipo_pag,
        "forma_pagamento": forma_pag,
        "itens": itens_formatados,
        "valor_total": vt_calc,
        "confianca_extracao": (confianca or "ALTO").upper(),
        "status_validacao": status_val,
        "divergencia_calculo": False,
        "origem_dados": "TEXTO",
        "transcricao_raw": f"Lançamento manual registrado via API: {formatar_brl(vt_calc)}.",
        "observacoes": observacoes or "",
    })

    if tipo_pag == FIADO_A_RECEBER and status_val == APROVADO:
        recalcular_saldo_cliente(cliente_id)

    c_atualizado = obter_cliente(cliente_id) or c
    lanc["cliente_nome"] = c_atualizado.get("nome", cliente_id)
    return lanc, c_atualizado


def atualizar_lancamento_manual(lancamento_id: str, payload_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Edita itens, valor, cliente, tipo ou forma de pagamento de um lançamento."""
    atual = obter_lancamento(lancamento_id)
    if not atual:
        raise NotFoundError(f"Lançamento '{lancamento_id}' não encontrado.")

    updates: Dict[str, Any] = {}
    cliente_antigo = atual.get("cliente_id")
    novo_cliente_id = payload_dict.get("cliente_id")

    if payload_dict.get("cliente") and not novo_cliente_id:
        c = obter_ou_criar_cliente(payload_dict["cliente"])
        novo_cliente_id = c["id"]

    if novo_cliente_id and novo_cliente_id != cliente_antigo:
        if not obter_cliente(novo_cliente_id):
            raise NotFoundError(f"Cliente '{novo_cliente_id}' não encontrado.")
        updates["cliente_id"] = novo_cliente_id

    if payload_dict.get("itens") is not None:
        novos_itens = [
            {
                "descricao": str(i.get("descricao", "Item"))[:200],
                "quantidade": float(i.get("quantidade", 1.0)),
                "valor_unitario": _f(i.get("valor_unitario", 0.0)),
                "valor_total_item": _f(float(i.get("quantidade", 1.0)) * float(i.get("valor_unitario", 0.0))),
            }
            for i in payload_dict["itens"]
        ]
        updates["itens"] = novos_itens
        updates["valor_total"] = _f(sum(i["valor_total_item"] for i in novos_itens))
        updates["divergencia_calculo"] = False
    elif payload_dict.get("valor_total") is not None:
        v_tot = _f(payload_dict["valor_total"])
        updates["valor_total"] = v_tot
        if not atual.get("itens"):
            updates["itens"] = [{"descricao": "Lançamento", "quantidade": 1.0, "valor_unitario": v_tot, "valor_total_item": v_tot}]

    tipo_in = payload_dict.get("tipo")
    forma_in = payload_dict.get("forma_pagamento")
    if tipo_in or forma_in:
        tipo_str = (tipo_in or ("FIADO" if atual.get("tipo_pagamento") == FIADO_A_RECEBER else "VENDA")).upper()
        forma_str = (forma_in or atual.get("forma_pagamento", "DINHEIRO")).upper()
        if forma_str == "CARTAO":
            forma_str = "CARTAO_CREDITO"
        if tipo_str == "FIADO" or forma_str == "FIADO":
            updates["tipo_operacao"] = VENDA
            updates["tipo_pagamento"] = FIADO_A_RECEBER
            updates["forma_pagamento"] = "FIADO"
        else:
            updates["tipo_operacao"] = VENDA
            updates["tipo_pagamento"] = PAGO
            updates["forma_pagamento"] = forma_str

    if payload_dict.get("status") is not None:
        st = payload_dict["status"].upper()
        if st in ("PENDENTE_CONFERENCIA", "PENDENTE_REVISAO"):
            updates["status_validacao"] = PENDENTE_REVISAO
        elif st in (APROVADO, "CANCELADO", REJEITADO):
            updates["status_validacao"] = st

    if payload_dict.get("observacoes") is not None:
        updates["observacoes"] = str(payload_dict["observacoes"])[:2000]

    atualizado = atualizar_lancamento(lancamento_id, updates)

    # Recalcula saldos se envolver fiado ou troca de cliente
    afetados = {cid for cid in [cliente_antigo, atualizado.get("cliente_id")] if cid}
    for cid in afetados:
        recalcular_saldo_cliente(cid)

    cliente_doc = obter_cliente(atualizado.get("cliente_id", ""))
    atualizado["cliente_nome"] = cliente_doc.get("nome") if cliente_doc else atualizado.get("cliente_id")
    atualizado["saldo_fiado_atual"] = cliente_doc.get("saldo_fiado_atual", 0.0) if cliente_doc else 0.0
    return atualizado


def aprovar_lancamento(lancamento_id: str, observacoes: Optional[str] = None) -> Dict[str, Any]:
    """Aprova um lançamento que estava na fila de conferência humana."""
    return validar_lancamento(
        lancamento_id=lancamento_id,
        status_validacao=APROVADO,
        observacoes=observacoes,
    )


def verificar_e_registrar_idempotencia_webhook(message_id: str, payload_resumo: Dict[str, Any]) -> bool:
    """Verifica se mensagem já foi processada (idempotência). Retorna True se for duplicada."""
    if not message_id:
        return False
    ref = get_db().collection(Collections.WEBHOOK_IDEMPOTENCIA).document(str(message_id))
    snap = ref.get()
    if snap.exists:
        return True
    ref.set({
        "message_id": str(message_id),
        "processado_em": agora_iso(),
        "payload_resumo": sanitizar_payload(payload_resumo),
    })
    return False


def testar_conexao_firestore() -> Tuple[bool, str]:
    """Testa se a conexão ativa com o Cloud Firestore está funcionando."""
    try:
        # Leitura rápida de 1 documento para aferição de socket/auth
        list(get_db().collection(Collections.CLIENTES).limit(1).stream())
        return True, "Conectado"
    except Exception as exc:
        return False, str(exc)
