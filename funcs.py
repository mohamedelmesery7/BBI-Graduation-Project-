import os
import json
import io
import pandas as pd
import streamlit as st
from openai import AzureOpenAI
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.storage.blob import BlobServiceClient

# Load environment variables from .env file
load_dotenv()

# Setup Azure OpenAI and Azure AI Search credentials
foundry_endpoint = os.getenv('FOUNDRY_ENDPOINT') or os.getenv('AZURE_OPENAI_ENDPOINT')
foundry_key = os.getenv('FOUNDRY_KEY') or os.getenv('AZURE_OPENAI_API_KEY')
chat_deployment = os.getenv('AZURE_OPENAI_CHAT_DEPLOYMENT_NAME', 'gpt-4o')
embedding_deployment = os.getenv('AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME', 'text-embedding-3-small')
search_endpoint = os.getenv('AZURE_SEARCH_ENDPOINT')
search_key = os.getenv('AZURE_SEARCH_KEY')
index_name = os.getenv('AZURE_SEARCH_INDEX') or os.getenv('AZURE_SEARCH_INDEX_NAME')

# Azure Blob Storage configurations
storage_connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
csv_container_name = os.getenv('CSV_CONTAINER_NAME', 'data')
csv_blob_name = os.getenv('CSV_BLOB_NAME', 'Test_Sample_Purchase_Requests.csv')

# Initialize Azure OpenAI Client
openai_client = AzureOpenAI(
    api_key=foundry_key,
    api_version="2024-06-01",
    azure_endpoint=foundry_endpoint
)

# Initialize and cache Azure Search client for performance
@st.cache_resource
def get_search_client():
    return SearchClient(
        endpoint=search_endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(search_key)
    )

def load_csv_from_blob():
    """Download and read the CSV dataset directly from Azure Blob Storage."""
    try:
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
        blob_client = blob_service_client.get_blob_client(container=csv_container_name, blob=csv_blob_name)
        blob_data = blob_client.download_blob().readall()
        df = pd.read_csv(io.BytesIO(blob_data))
        return df
    except Exception as e:
        raise Exception(f"Failed to load CSV from Azure Blob Storage: {str(e)}")

def validate_purchase_request_from_csv(request_id: str):
    """
    Reads the CSV dataset from Azure Blob Storage and validates 
    the purchase request fields and pricing rules based on official policy.
    """
    try:
        df = load_csv_from_blob()
        
        # Clean column names from any extra spaces
        df.columns = df.columns.str.strip()
        
        # Filter dataframe using PR_ID column
        req = df[df['PR_ID'].astype(str).str.strip() == str(request_id).strip()]
        
        if req.empty:
            return {"error": f"Request ID {request_id} not found in dataset."}
        
        row = req.iloc[0]
        
        required_fields = {
            "Business_Justification": row.get("Business_Justification"),
            "Budget_Code": row.get("Budget_Code"),
        }
        approval_level = row.get("Approval_Level")
        quotes_count = pd.to_numeric(row.get("Quotes_Attached_Count"), errors="coerce")
        req_value = pd.to_numeric(row.get("Amount_AED"), errors="coerce")
        quotes_status = "Pass" if req_value <= 25000 or quotes_count >= 3 else f"Fail: Value is {req_value} AED (>=25k) and quotes are {quotes_count} (at least 3 required)"

        missing_fields = [
            field_name
            for field_name, value in required_fields.items()
            if pd.isna(value) or str(value).strip() == ""
        ]
        policy_violations = []

        if pd.isna(req_value):
            missing_fields.append("Amount_AED")
        elif quotes_status != "Pass":
            policy_violations.append(quotes_status)
            missing_fields.append("Quotes_Attached_Count")

        missing_fields = list(dict.fromkeys(missing_fields))
        is_complete = not missing_fields and not policy_violations
        approval_value = (
            str(approval_level).strip()
            if pd.notna(approval_level) and str(approval_level).strip()
            else "Not Applicable"
        )
        recommended_action = (
            "Proceed with the approval process as the request is complete and meets all requirements."
            if is_complete
            else "Return the request to the requester to provide the missing information and resolve the policy violations."
        )

        results = {
            "PR_ID": str(request_id),
            "is_complete": is_complete,
            "required_approval_level": approval_value,
            "missing_fields": missing_fields or ["None"],
            "policy_violations": policy_violations,
            "recommended_action": recommended_action,
            "source": csv_blob_name,
            "tool_used": "validate_purchase_request_from_csv",
        }
        return results

    except Exception as e:
        return {"error": str(e)}

def render_assistant_response(content):
    """Display schema responses as readable assistant messages."""
    try:
        response_data = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        st.markdown(content)
        return

    if not isinstance(response_data, dict):
        st.markdown(content)
        return

    if "pr_id" in response_data:
        st.markdown(f"**Purchase Request:** `{response_data.get('pr_id', '')}`")
        if response_data.get("is_complete"):
            st.success("Ready for processing")
        else:
            st.warning("Not ready for processing")

        approval_level = response_data.get("required_approval_level")
        if approval_level:
            st.markdown(f"**Required approval level:** {approval_level}")

        missing_fields = response_data.get("missing_fields") or ["None"]
        st.markdown("**Missing fields**\n\n" + "\n".join(f"- {field}" for field in missing_fields))

        policy_violations = response_data.get("policy_violations", [])
        if policy_violations:
            st.markdown("**Policy violations**\n\n" + "\n".join(f"- {item}" for item in policy_violations))

        st.markdown(f"**Recommended action**\n\n{response_data.get('recommended_action', '')}")
        st.caption(f"Source: {csv_blob_name} (Azure Blob Storage)")
        st.caption("Tool used: validate_purchase_request_from_csv")
        return

    answer = response_data.get("answer", "").replace("\\n", "\n")
    if answer:
        st.markdown(answer)

    missing_information = response_data.get("missing_information", [])
    if missing_information:
        st.markdown("**Missing information**\n\n" + "\n".join(f"- {item}" for item in missing_information))

    next_action = response_data.get("recommended_next_action", "")
    if next_action:
        st.markdown(f"**Recommended next action**\n\n{next_action}")

    source_documents = response_data.get("source_documents", [])
    if source_documents:
        st.markdown("**Sources**\n\n" + "\n".join(f"- {source}" for source in source_documents))

# Define the function specification for OpenAI Tool/Function Calling
tools = [
    {
        "type": "function",
        "function": {
            "name": "validate_purchase_request_from_csv",
            "description": "Validates a purchase request checklist fields and checks the CSV dataset from Azure Blob Storage for quote requirements based on request id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "The unique ID of the purchase request to validate."}
                },
                "required": ["request_id"]
            }
        }
    }
]

# Function to retrieve context via Hybrid Search (Vector + Keyword) returning real titles
def retrieve_context(question, search_client, top_k=3):
    try:
        embedding_response = openai_client.embeddings.create(
            input=question,
            model=embedding_deployment
        )
        query_vector = embedding_response.data[0].embedding

        vector_query = VectorizedQuery(
            vector=query_vector,
            k_nearest_neighbors=top_k,
            fields="text_vector"
        )

        results = search_client.search(
            search_text=question,
            vector_queries=[vector_query],
            select=["chunk", "title"],
            top=top_k
        )

        context_parts = []
        for result in results:
            source = result.get("title", "Unknown_Document")
            content = result.get("chunk", "")
            if content:
                context_parts.append(f"[Source Document: {source}]\n{content}")

        return "\n\n---\n\n".join(context_parts) if context_parts else ""
    except Exception as e:
        return f"[Search Error: {str(e)}]"




schema_container_name = os.getenv('SCHEMA_CONTAINER_NAME', 'schemas')
logo_blob_name = os.getenv('LOGO_BLOB_NAME', 'BBI_logo-removebg-preview.png')
validation_schema_blob = os.getenv('VALIDATION_SCHEMA_BLOB', 'purchase_request_validation_schema_2.json')

@st.cache_data
def load_logo_from_blob():
    """Download the company logo from the schema container."""
    try:
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
        blob_client = blob_service_client.get_blob_client(
            container=schema_container_name,
            blob=logo_blob_name
        )
        return blob_client.download_blob().readall()
    except Exception as e:
        raise Exception(f"Failed to load logo {logo_blob_name} from Azure Blob Storage: {str(e)}")

def load_json_schema_from_blob(blob_name: str):
    """Download and parse a JSON schema file directly from Azure Blob Storage."""
    try:
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
        blob_client = blob_service_client.get_blob_client(
            container=schema_container_name,
            blob=blob_name
        )
        blob_data = blob_client.download_blob().readall()
        return json.loads(blob_data.decode('utf-8'))
    except Exception as e:
        raise Exception(f"Failed to load schema {blob_name} from Azure Blob Storage: {str(e)}")

