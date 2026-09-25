# BBI Procurement AI Assistant

AI-powered procurement assistant built with Streamlit, Azure OpenAI, Azure AI Search, and Azure Blob Storage.

## Features

- Answers procurement policy questions using RAG from indexed PDF documents.
- Summarizes vendor documents and extracts vendor information.
- Uses hybrid Azure AI Search with keyword and vector retrieval.
- Validates purchase requests using CSV data stored in Azure Blob Storage.
- Applies deterministic Python validation for required fields and quotation rules.
- Uses the LLM to explain Python validation results in the validation response schema.
- Loads the validation response schema from Azure Blob Storage.
- Loads the BBI company logo from Azure Blob Storage.
- Displays the CSV source and validation tool after validation responses.

## Architecture

```text
User question
    |
    v
Azure AI Search hybrid retrieval
    |
    +--> General question: retrieved PDF context -> Azure OpenAI answer
    |
    +--> Purchase request question:
             CSV Blob Storage -> Python validation -> validation schema -> LLM explanation
```

For validation, Python is the source of truth for:

- Request completeness
- Missing fields
- Policy violations
- Approval level
- Quotation rule
- Recommended action

The LLM formats and explains the deterministic validation result. It must not replace the Python validation decision.

## Project Files

```text
Final/
|-- Ragapp.py                 Streamlit application and chat workflow
|-- funcs.py                  Azure clients, retrieval, CSV validation, rendering helpers
|-- requirements.txt          Python dependencies
|-- documents/                Local reference PDFs for development/testing
|-- old answer screens/       Optional screenshots for presentation reference
|-- .env                      Local secrets; do not commit this file
```

## Prerequisites

- Python 3.10 or newer
- Azure OpenAI resource or Azure AI Foundry deployment
- Azure AI Search service with an indexed PDF knowledge base
- Azure Blob Storage account
- CSV blob containing purchase requests
- Validation JSON schema blob
- Logo blob in the configured schema container

## Installation

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment Variables

Create a local `.env` file in the project root. Never commit it to GitHub.

```env
FOUNDRY_ENDPOINT=https://your-openai-resource.openai.azure.com/
FOUNDRY_KEY=your-secret-key
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=your-chat-deployment
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small

AZURE_SEARCH_ENDPOINT=https://your-search-service.search.windows.net
AZURE_SEARCH_KEY=your-search-key
AZURE_SEARCH_INDEX=your-index-name

AZURE_STORAGE_CONNECTION_STRING=your-storage-connection-string
CSV_CONTAINER_NAME=data
CSV_BLOB_NAME=Test_Sample_Purchase_Requests.csv

SCHEMA_CONTAINER_NAME=schemas
VALIDATION_SCHEMA_BLOB=purchase_request_validation_schema_2.json
LOGO_BLOB_NAME=BBI_logo-removebg-preview.png
```

The application reads these values with `os.getenv()`. In Azure App Service, configure the same names under **Settings > Environment variables > App settings** instead of uploading `.env`.

## Run Locally

```bash
streamlit run Ragapp.py
```

The application normally opens at:

```text
http://localhost:8501
```

## Retrieval and RAG

`retrieve_context()` creates an embedding for the user question and performs hybrid search using keyword text and vector similarity. It retrieves the `chunk` and `title` fields from Azure AI Search and sends the selected context to Azure OpenAI.

The chunk size, overlap, vector dimensions, semantic configuration, and indexer skillset are configured in Azure AI Search rather than in the Streamlit UI code. Make sure the indexer embedding model and query embedding model are compatible.

## Purchase Request Validation

The validation tool is declared in `funcs.py` and accepts a purchase request ID:

```text
validate_purchase_request_from_csv(request_id)
```

The function:

1. Downloads the CSV from Azure Blob Storage.
2. Finds the matching `PR_ID`.
3. Checks required fields such as `Business_Justification` and `Budget_Code`.
4. Reads `Amount_AED`, `Quotes_Attached_Count`, and `Approval_Level`.
5. Applies the quotation rule:

```python
quotes_status = "Pass" if req_value <= 25000 or quotes_count >= 3 else "Fail..."
```

6. Returns the validation result used by the response schema.

The validation schema is loaded from Azure Blob Storage using `VALIDATION_SCHEMA_BLOB`.

## Azure App Service Deployment

1. Create a Linux Azure App Service with Python 3.11.
2. Deploy the project through GitHub, ZIP Deploy, or the VS Code Azure extension.
3. Add the environment variables under **App Service > Settings > Environment variables**.
4. Do not upload `.env` or commit it to GitHub.
5. Configure this startup command:

```bash
python -m streamlit run Ragapp.py --server.address 0.0.0.0 --server.port 8000 --server.headless true
```

6. Save the configuration and restart the App Service.
7. Use **Monitoring > Log stream** to diagnose startup or Azure connection errors.

## GitHub Safety

Use a private repository and add a `.gitignore` file:

```gitignore
.env
.venv/
__pycache__/
*.pyc
.streamlit/
```

Never commit Azure keys, storage connection strings, or other secrets.

## Testing and Evaluation

Test at least these categories:

- Procurement policy questions
- Vendor onboarding requirements
- Vendor profile summaries
- Vendor trade license extraction
- Missing purchase request fields
- Purchase request validation
- Procurement officer summaries



## Risks and Limitations

- Inaccurate retrieval can cause incomplete answers.
- PDF text extraction may lose tables or formatting.
- The LLM can still hallucinate unsupported details in general answers.
- Validation depends on the freshness and quality of the CSV.
- Hardcoded Python rules must be updated when procurement policy changes.
- Azure service availability and permissions affect application availability.
- Important procurement decisions require human review.

## Security Notes

- Keep `.env` local only.
- Use App Service settings or Azure Key Vault for production secrets.
- Use private Blob containers and Search indexes where possible.
- Apply least-privilege access to Azure resources.
- Do not expose storage connection strings or API keys in screenshots or presentations.
