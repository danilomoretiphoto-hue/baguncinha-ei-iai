"""Script de teste de extração multimodal financeira com a SDK google-genai (Gemini 2.5 Flash).

Envia um texto de pedido/comanda de balcão e valida a conversão em JSON estruturado.
"""

import asyncio
import json
import sys
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path para importação de app
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import settings
from app.services.gemini_service import extrair_de_texto, normalizar_extracao


async def testar():
    print("=" * 65)
    print("🧪 TESTE DE EXTRAÇÃO MULTIMODAL — GEMINI 2.5 FLASH")
    print("=" * 65)

    if not settings.GEMINI_API_KEY:
        print("❌ ERRO: GEMINI_API_KEY não foi encontrada no arquivo .env.")
        print("Por favor, adicione sua chave de API no arquivo .env e tente novamente.")
        sys.exit(1)

    texto_exemplo = (
        "Marcar pro João do Bar 3 guarana antarctica lata 15 real "
        "e 1 x-tudo 22 real paga semana que vem"
    )

    print(f"\n📝 Texto de Entrada (Nota de Balcão):\n'{texto_exemplo}'\n")
    print(f"🤖 Modelo em uso: {settings.GEMINI_MODEL}")
    print("⏳ Enviando para o Gemini via google-genai...")

    try:
        # Extração direta estruturada via SDK oficial
        extracao = await extrair_de_texto(texto_exemplo)
        print("\n✔ Resposta bruta recebida com sucesso do Gemini!")

        # Normalização com as regras de balcão e auditoria financeira
        normalizado = normalizar_extracao(extracao)

        print("\n📋 DADOS ESTRUTURADOS EXTRAÍDOS (JSON):")
        print("-" * 65)
        print(json.dumps(normalizado, indent=2, ensure_ascii=False))
        print("-" * 65)

        print("\n🔍 VALIDAÇÃO DAS REGRAS DE NEGÓCIO:")
        print(f"  • Cliente Detectado: {normalizado['cliente_nome']}")
        print(f"  • Tipo de Operação:  {normalizado['tipo_operacao']}")
        print(f"  • Tipo de Pagamento: {normalizado['tipo_pagamento']}")
        print(f"  • Forma de Pagamento:{normalizado['forma_pagamento']}")
        print(f"  • Valor Total:       R$ {normalizado['valor_total']:.2f}")
        print(f"  • Confiança da IA:   {normalizado['confianca_extracao']}")
        print(f"  • Status Validação:  {normalizado['status_validacao']}")
        print(f"  • Divergência:       {'SIM' if normalizado['divergencia_calculo'] else 'NÃO'}")

        print("\n✅ TESTE CONCLUÍDO COM SUCESSO! A IA respondeu dentro do contrato financeiro.")

    except Exception as exc:
        print(f"\n❌ FALHA NO TESTE: {exc}")
        print("Verifique se sua GEMINI_API_KEY é válida e tem acesso ao modelo gemini-2.5-flash.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(testar())
