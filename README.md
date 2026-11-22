# 🧾 Agente Like Baguncinha

Sistema inteligente de gerenciamento de comandas, lançamentos diários, controle de fiados e prestação de contas automatizada para o comércio **Like Baguncinha**, localizado em **Bebedouro - SP**.

Construído com **Python 3.11+**, **FastAPI**, **Firebase Firestore (Spark Free Tier)**, **SDK oficial google-genai (Gemini 2.5 Flash)** e uma interface SPA moderna em **Bento Grid & Glassmorphism**.

---

## 🚀 Arquitetura e Recursos

1. **Ingestão Multimodal Inteligente (Gemini 2.5 Flash)**:
   - Lê fotos de comandas manuscritas, papéis de rascunho, recibos e notas fiscais.
   - Ouve e transcreve áudios de pedidos e acertos enviados via WhatsApp (OGG Opus, MP3, WAV, M4A).
   - Ingestão instantânea de texto livre de balcão (gírias, quantidades e preços).
   - Validação matemática automática: soma de `(quantidade * valor_unitario)` com detecção de divergências.

2. **Regras Financeiras de Balcão**:
   - Classificação estrita: `PAGO` (dinheiro, PIX, cartão), `FIADO_A_RECEBER` e `A_PAGAR` (despesas/fornecedores).
   - Fiados só deixam o saldo devedor mediante lançamento explícito de `PAGAMENTO_FIADO` (baixa por FIFO).
   - Níveis de confiança da IA (`ALTO`, `MEDIO`, `BAIXO`): lançamentos com incerteza caem na **Fila de Conferência Humana** com status `PENDENTE_REVISAO`.

3. **Arquitetura Spark Tier (Firebase Gratuito)**:
   - Respeita o limite do plano Spark: **nunca** armazena arquivos pesados ou strings base64 no Firestore.
   - Grava apenas metadados estruturados (JSON).

4. **Painel Web Administrativo SPA**:
   - Layout **Bento Grid** em tema escuro (`#0F172A`) com efeito **Glassmorphism**.
   - 4 Cards de KPIs em tempo real (Total Vendido Hoje, Fiado a Receber, Recebido de Fiado, Pendências IA).
   - Área drag-and-drop para imagens e áudios + caixa de texto rápido de balcão.
   - Fila de conferência humana com botões rápidos de "Aprovar Lançamento" e "Editar/Rejeitar".
   - Tabela de Clientes com cálculo de fiado e botão **"Cobrar via WhatsApp"** (gera mensagem formatada e link direto).
   - Tabela de lançamentos com busca em tempo real e filtros.
   - Exportação completa do fechamento diário em planilha **Excel (.xlsx)** com abas de Resumo e Detalhamento.

5. **APIs Seguras**:
   - **Pública do Cliente (`/v1/consulta/*`)**: protegida por token individual `X-API-Key` (resumo de conta, saldo em aberto e extrato).
   - **Administrativa (`/v1/admin/*`)**: protegida por chave mestra `X-Admin-Key`.
   - **Webhook WhatsApp (`/v1/whatsapp/webhook`)**: compatível com Z-API, Evolution API, Meta Cloud API e provedores genéricos.

---

## 📁 Estrutura de Arquivos

```
agente-like-baguncinha/
├── .env.example
├── .gitignore
├── firebase.json
├── firestore.rules
├── requirements.txt
├── README.md
├── serviceAccountKey.json        # Chave de conta de serviço Firebase (adicionada pelo usuário)
├── app/
│   ├── __init__.py
│   ├── main.py                   # Ponto de entrada FastAPI, CORS e Lifespan
│   ├── config.py                 # Leitura de variáveis de ambiente e fuso SP
│   ├── database.py               # Singleton Firestore (Firebase Admin SDK)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── cliente.py            # Schemas Pydantic de clientes e cobrança
│   │   ├── lancamento.py         # Schemas de lançamentos, itens e IA
│   │   ├── fechamento.py         # Schemas de fechamento diário e KPIs
│   │   └── webhook.py            # Schemas de mensagens WhatsApp e logs
│   ├── services/
│   │   ├── __init__.py
│   │   ├── gemini_service.py     # Prompt do Gemini 2.5 Flash via google-genai
│   │   ├── firestore_service.py  # Operações e regras financeiras no Firestore
│   │   └── export_service.py     # Geração de planilhas Excel (.xlsx) com OpenPyXL
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py             # Health check /health
│   │   ├── admin.py              # Endpoints administrativos (/v1/admin/*)
│   │   ├── consulta.py           # Endpoints públicos do cliente (/v1/consulta/*)
│   │   └── whatsapp.py           # Webhook WhatsApp (/v1/whatsapp/webhook)
│   └── static/
│       ├── index.html            # SPA Bento Grid
│       ├── styles.css            # Tema escuro e Glassmorphism
│       └── app.js                # Lógica e reatividade JS Vanilla (ES6+)
└── scripts/
    ├── seed_demo.py              # População de dados de teste (clientes e lançamentos)
    └── testar_extracao.py        # Teste CLI de extração da IA Gemini 2.5 Flash
```

---

## 🛠️ Passo a Passo para Instalação e Execução

### 1. Configurar Credenciais
Crie o arquivo `.env` na raiz copiando de `.env.example`:

```bash
cp .env.example .env
```

Preencha os valores:
```env
GEMINI_API_KEY=AIzaSy...SuaChaveGeminiAqui
FIREBASE_PROJECT_ID=seu-projeto-firebase-id
ADMIN_MASTER_KEY=sua_chave_mestra_para_painel_admin_123
WEBHOOK_SECRET_TOKEN=seu_token_secreto_whatsapp
PORT=8000
ENVIRONMENT=development
```

Coloque sua chave do Firebase baixada no console na raiz do projeto com o nome:
`serviceAccountKey.json`

### 2. Instalar Dependências no Ambiente Virtual
```bash
# Criar ambiente virtual
python -m venv venv

# Ativar no Windows:
.\venv\Scripts\activate
# Ativar no Linux/macOS:
source venv/bin/activate

# Instalar dependências
pip install -r requirements.txt
```

### 3. Testar Extração com Gemini 2.5 Flash
Valide se sua chave de IA está funcionando:
```bash
python scripts/testar_extracao.py
```

### 4. Popular o Banco com Dados de Teste (Seed)
```bash
python scripts/seed_demo.py
```
*Guarde a `X-API-Key` impressa no terminal para testar a rota pública de clientes.*

### 5. Iniciar o Servidor FastAPI
```bash
uvicorn app.main:app --reload --port 8000
```

- **Painel Administrativo Web**: [http://localhost:8000/](http://localhost:8000/)
- **Documentação Swagger**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 🔒 Testando as Rotas da API

### Consulta do Cliente (com `X-API-Key` gerada no seed)
```bash
curl -X GET "http://localhost:8000/v1/consulta/resumo" \
     -H "X-API-Key: SUACHAVECLIENTEGERADANOSEED"
```

### Ingestão de Texto Administrativa (com `X-Admin-Key`)
```bash
curl -X POST "http://localhost:8000/v1/admin/ingestao/texto" \
     -H "X-Admin-Key: sua_chave_mestra_para_painel_admin_123" \
     -H "Content-Type: application/json" \
     -d '{"texto": "Marcar pro João do Bar 2 cervejas heineken a 12 reais cada pago semana que vem"}'
```

### Exportar Fechamento em Excel (.xlsx)
```bash
curl -X GET "http://localhost:8000/v1/admin/fechamento/exportar-xlsx" \
     -H "X-Admin-Key: sua_chave_mestra_para_painel_admin_123" \
     --output fechamento.xlsx
```

---

## 🌐 Publicação no Firebase Hosting

O frontend é uma SPA estática independente pronta para o Firebase Hosting:
```bash
firebase login
firebase init hosting
firebase deploy --only hosting
```
