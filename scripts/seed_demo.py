"""Script de população inicial (seed) para ambiente de desenvolvimento/demonstração.

Cadastra:
- 2 clientes de teste: "João do Bar" e "Maria das Marmitas"
- 5 lançamentos de demonstração:
    1. Venda Paga PIX (João do Bar)
    2. Venda Paga PIX (Maria das Marmitas)
    3. Fiado a Receber (João do Bar)
    4. Fiado a Receber (Maria das Marmitas)
    5. Despesa de Fornecedor (Distribuidora de Bebidas Bebedouro)
"""

import sys
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path para importação de app
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.database import Collections, get_db, init_firebase
from app.services import firestore_service as fs


def main():
    print("=" * 60)
    print("🌱 AGENTE LIKE BAGUNCINHA — POPULAÇÃO INICIAL (SEED DEMO)")
    print("=" * 60)

    try:
        init_firebase()
        db = get_db()
        print("✔ Conexão com Firebase Firestore estabelecida.\n")
    except Exception as exc:
        print(f"❌ Erro ao conectar ao Firebase: {exc}")
        print("Certifique-se de que o arquivo 'serviceAccountKey.json' está presente ou as credenciais estão configuradas.")
        sys.exit(1)

    print("1. Cadastrando clientes de demonstração...")

    # Cliente 1: João do Bar
    joao = fs.buscar_cliente_por_nome("João do Bar")
    if not joao:
        joao = fs.criar_cliente(
            nome="João do Bar",
            telefone="5517999991111",
            cpf_cnpj="123.456.789-00",
            cliente_id="joao-do-bar",
        )
        print("  ➕ Cliente criado: João do Bar")
    else:
        print("  ℹ Cliente já existente: João do Bar")

    # Cliente 2: Maria das Marmitas
    maria = fs.buscar_cliente_por_nome("Maria das Marmitas")
    if not maria:
        maria = fs.criar_cliente(
            nome="Maria das Marmitas",
            telefone="5517999992222",
            cpf_cnpj="987.654.321-99",
            cliente_id="maria-das-marmitas",
        )
        print("  ➕ Cliente criado: Maria das Marmitas")
    else:
        print("  ℹ Cliente já existente: Maria das Marmitas")

    print("\n2. Inserindo 5 lançamentos de demonstração...")

    # Lançamento 1: Venda Paga no PIX (João do Bar)
    l1 = fs.salvar_lancamento({
        "cliente_id": joao["id"],
        "tipo_operacao": "VENDA",
        "tipo_pagamento": "PAGO",
        "forma_pagamento": "PIX",
        "itens": [
            {"descricao": "Cerveja Heineken Long Neck", "quantidade": 2, "valor_unitario": 12.0},
            {"descricao": "Porção de Batata Frita", "quantidade": 1, "valor_unitario": 28.0},
        ],
        "confianca_extracao": "ALTO",
        "status_validacao": "APROVADO",
        "divergencia_calculo": False,
        "origem_dados": "TEXTO",
        "transcricao_raw": "João do Bar consumiu 2 Heineken a 12 reais e 1 batata frita 28, pago no Pix",
        "observacoes": "Consumo de balcão pago via chave Pix",
    })
    print(f"  ✔ [1/5] Venda Paga PIX: R$ {l1['valor_total']:.2f} (João do Bar)")

    # Lançamento 2: Venda Paga no PIX (Maria das Marmitas)
    l2 = fs.salvar_lancamento({
        "cliente_id": maria["id"],
        "tipo_operacao": "VENDA",
        "tipo_pagamento": "PAGO",
        "forma_pagamento": "PIX",
        "itens": [
            {"descricao": "Marmitex Executiva Especial", "quantidade": 2, "valor_unitario": 25.0},
            {"descricao": "Refrigerante Coca-Cola 2L", "quantidade": 1, "valor_unitario": 14.0},
        ],
        "confianca_extracao": "ALTO",
        "status_validacao": "APROVADO",
        "divergencia_calculo": False,
        "origem_dados": "TEXTO",
        "transcricao_raw": "Maria das Marmitas comprou 2 marmitex executiva 25 cada e 1 coca 2L 14 reais, pago no Pix",
        "observacoes": "Retirada no balcão paga via Pix",
    })
    print(f"  ✔ [2/5] Venda Paga PIX: R$ {l2['valor_total']:.2f} (Maria das Marmitas)")

    # Lançamento 3: Fiado a Receber (João do Bar)
    l3 = fs.salvar_lancamento({
        "cliente_id": joao["id"],
        "tipo_operacao": "VENDA",
        "tipo_pagamento": "FIADO_A_RECEBER",
        "forma_pagamento": "FIADO",
        "itens": [
            {"descricao": "X-Tudo Especial da Casa", "quantidade": 1, "valor_unitario": 26.0},
            {"descricao": "Guaraná Antarctica Lata", "quantidade": 2, "valor_unitario": 6.0},
        ],
        "confianca_extracao": "ALTO",
        "status_validacao": "APROVADO",
        "divergencia_calculo": False,
        "origem_dados": "IMAGEM_COMANDA",
        "transcricao_raw": "Marcar pro João do Bar 1 x-tudo 26 e 2 guarana lata 6 conto cada",
        "observacoes": "Comanda manuscrita assinada pelo cliente para acerto no sábado",
    })
    print(f"  ✔ [3/5] Fiado a Receber: R$ {l3['valor_total']:.2f} (João do Bar)")

    # Lançamento 4: Fiado a Receber (Maria das Marmitas)
    l4 = fs.salvar_lancamento({
        "cliente_id": maria["id"],
        "tipo_operacao": "VENDA",
        "tipo_pagamento": "FIADO_A_RECEBER",
        "forma_pagamento": "FIADO",
        "itens": [
            {"descricao": "Fardo de Água Mineral 500ml", "quantidade": 1, "valor_unitario": 24.0},
            {"descricao": "Pacote de Guardanapo", "quantidade": 3, "valor_unitario": 5.0},
        ],
        "confianca_extracao": "ALTO",
        "status_validacao": "APROVADO",
        "divergencia_calculo": False,
        "origem_dados": "AUDIO_WHATSAPP",
        "transcricao_raw": "Ô Danilo marca na minha conta um fardo de água 24 e três pacote de guardanapo a 5 real que passo aí depois",
        "observacoes": "Áudio WhatsApp transcrito com precisão",
    })
    print(f"  ✔ [4/5] Fiado a Receber: R$ {l4['valor_total']:.2f} (Maria das Marmitas)")

    # Lançamento 5: Despesa de Fornecedor
    desp_cliente = fs.garantir_cliente_sistema("despesas-internas", "Like Baguncinha (Despesas Internas)")
    l5 = fs.salvar_lancamento({
        "cliente_id": desp_cliente["id"],
        "tipo_operacao": "DESPESA",
        "tipo_pagamento": "A_PAGAR",
        "forma_pagamento": "DINHEIRO",
        "itens": [
            {"descricao": "Entrega Distribuidora de Gelo e Carvão Bebedouro", "quantidade": 1, "valor_unitario": 110.0},
        ],
        "confianca_extracao": "ALTO",
        "status_validacao": "APROVADO",
        "divergencia_calculo": False,
        "origem_dados": "TEXTO",
        "transcricao_raw": "Fornecedor de Gelo e Carvão: 1 entrega no valor de 110 reais a pagar em dinheiro na entrega",
        "observacoes": "Fornecedor: Distribuidora de Gelo Bebedouro",
    })
    print(f"  ✔ [5/5] Despesa Fornecedor: R$ {l5['valor_total']:.2f}")

    # Atualiza saldos devedores de fiado
    saldo_joao = fs.recalcular_saldo_cliente(joao["id"])
    saldo_maria = fs.recalcular_saldo_cliente(maria["id"])

    print("\n" + "=" * 60)
    print("🎉 SEED CONCLUÍDO COM SUCESSO!")
    print("=" * 60)
    print("\n🔑 CREDENCIAIS GERADAS PARA TESTES DA API PÚBLICA (/v1/consulta/*):\n")
    print(f"👤 Cliente: {joao['nome']}")
    print(f"   ID: {joao['id']}")
    print(f"   Saldo Fiado: R$ {saldo_joao:.2f}")
    print(f"   X-API-Key: {joao['api_key']}")
    print(f"   Exemplo de teste:")
    print(f"""   curl -H "X-API-Key: {joao['api_key']}" http://localhost:8000/v1/consulta/resumo\n""")

    print(f"👤 Cliente: {maria['nome']}")
    print(f"   ID: {maria['id']}")
    print(f"   Saldo Fiado: R$ {saldo_maria:.2f}")
    print(f"   X-API-Key: {maria['api_key']}")
    print(f"   Exemplo de teste:")
    print(f"""   curl -H "X-API-Key: {maria['api_key']}" http://localhost:8000/v1/consulta/resumo\n""")
    print("=" * 60)


if __name__ == "__main__":
    main()
