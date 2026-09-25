import base64
import json
import streamlit as st
from funcs import (
    openai_client,
    chat_deployment,
    get_search_client,
    retrieve_context,
    validate_purchase_request_from_csv,
    tools,
    load_json_schema_from_blob,
    validation_schema_blob,
    render_assistant_response,
    load_logo_from_blob
)

# --- Streamlit UI Setup ---
st.set_page_config(page_title="BBI Procurement Assistant", page_icon="💬", layout="centered")
st.markdown("""
<style>
    :root {
        --bbi-blue: #074367;
        --bbi-green: #45BE4F;
        --bbi-white: #FFFFFF;
        --bbi-blue-soft: #EEF5F8;
    }

    .stApp {
        background:
            linear-gradient(135deg, rgba(69, 190, 79, 0.08), transparent 34%),
            linear-gradient(315deg, rgba(7, 67, 103, 0.08), transparent 42%),
            linear-gradient(rgba(7, 67, 103, 0.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(7, 67, 103, 0.035) 1px, transparent 1px),
            #F7FAFB;
        background-size: auto, auto, 28px 28px, 28px 28px, auto;
        background-attachment: fixed;
        color: var(--bbi-blue);
    }

    [data-testid="stHeader"] {
        background: rgba(255, 255, 255, 0.82);
        backdrop-filter: blur(8px);
    }

    [data-testid="stAppViewContainer"] {
        background: transparent;
    }

    [data-testid="stMain"] {
        background: rgba(255, 255, 255, 0.68);
        border-left: 1px solid rgba(7, 67, 103, 0.06);
        border-right: 1px solid rgba(7, 67, 103, 0.06);
    }

    .bbi-header {
        display: flex;
        align-items: center;
        gap: 18px;
        padding: 12px 0 22px;
        border-bottom: 3px solid var(--bbi-green);
        background: rgba(255, 255, 255, 0.72);
        border-radius: 0 0 14px 14px;
        margin-bottom: 22px;
    }

    .bbi-logo {
        width: 78px;
        height: 78px;
        object-fit: contain;
    }

    .bbi-title {
        color: var(--bbi-blue);
        font-size: 2rem;
        font-weight: 700;
        line-height: 1.1;
        margin: 0;
    }

    .bbi-subtitle {
        color: #4D6877;
        font-size: 0.98rem;
        margin: 7px 0 0;
    }

    [data-testid="stChatMessage"] {
        border-radius: 12px;
        border: 1px solid #DCE8ED;
        margin-bottom: 14px;
    }

    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background: var(--bbi-blue-soft);
    }

    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
        background: var(--bbi-white);
        border-left: 4px solid var(--bbi-green);
    }

    [data-testid="stChatInput"] {
        border-top: 2px solid var(--bbi-green);
    }

    .stButton > button {
        background: var(--bbi-green);
        color: var(--bbi-white);
        border: 0;
    }

    h1, h2, h3, strong {
        color: var(--bbi-blue);
    }
</style>
""", unsafe_allow_html=True)

try:
    logo_bytes = load_logo_from_blob()
    logo_markup = f'<img class="bbi-logo" src="data:image/png;base64,{base64.b64encode(logo_bytes).decode("ascii")}">' 
except Exception:
    logo_markup = ""

st.markdown(f"""
<div class="bbi-header">
    {logo_markup}
    <div>
        <p class="bbi-title">BBI Procurement Assistant</p>
        <p class="bbi-subtitle">Policy-aware procurement guidance powered by Azure.</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Initialize and check Azure Search Client
try:
    search_client = get_search_client()
except Exception as ex:
    st.error(f"Error connecting to Azure Search: {ex}")
    st.stop()

# Initialize chat history in session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display past messages
for message in st.session_state.messages:
    if message["role"] != "system":
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_assistant_response(message["content"])
            else:
                st.markdown(message["content"])

# User input handling
user_input = st.chat_input("Type your inquiry or validation request (e.g., What documents are required? or Validate request #102)...")

if user_input:
    # Append user message to history
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.spinner("Processing request, searching documents, and querying Azure Blob Storage..."):
        
        # 1. Retrieve relevant text chunks and real file names via Azure AI Search
        retrieved_context = retrieve_context(
            user_input, search_client, top_k=8
        )

        validation_schema = load_json_schema_from_blob(validation_schema_blob)

        # 2. Build system instructions dynamically including the retrieved context
        system_instruction = f"""You are a procurement assistant. Answer questions using only the provided procurement policy, vendor onboarding guide, purchase request guidelines, supplier code of conduct, vendor documents, and purchase request dataset. Do not invent, assume, or add approval requirements that are not supported by the provided context.

    If information is missing, state exactly what is missing and recommend the next procurement action. Do not approve requests by yourself.

    CRITICAL RULE FOR VALIDATION TASKS:
    If the user asks to validate a purchase request or perform any validation task, you MUST call the provided validation tool, such as validate_purchase_request_from_csv, to query the purchase request dataset. Compare the tool result with the relevant purchase request guidelines, but treat the tool result as authoritative for the validation outcome.

    For validation responses, do not infer, recalculate, change, or replace any of these tool-result fields: pr_id, is_complete, required_approval_level, missing_fields, policy_violations, recommended_action, source, or tool_used. Explain the result only and recommend the next procurement action when required.

    SOURCE RULE:
    At the very end of every response, add exactly one breif section titled "Sources". Keep all source references together only in the final "Sources" section.sources only include the file names of the retrieved documents that were used to answer the question. 
    Retrieved Enterprise Context:
    {retrieved_context}
    """

        # Prepare messages payload for LLM
        messages_payload = [{"role": "system", "content": system_instruction}] + st.session_state.messages

        # First API call to model with tools enabled
        response = openai_client.chat.completions.create(
            model=chat_deployment,
            messages=messages_payload,
            tools=tools,
            tool_choice="auto",
            temperature=0.3
        )
        
        response_message = response.choices[0].message

        # Check if the model wants to call a tool/function (e.g., CSV validation from Blob)
        if response_message.tool_calls:
            messages_payload.append(response_message)
            validation_result = None
            
            for tool_call in response_message.tool_calls:
                if tool_call.function.name == "validate_purchase_request_from_csv":
                    function_args = json.loads(tool_call.function.arguments)
                    
                    # Execute the local python function fetching CSV from Blob Storage
                    function_response = validate_purchase_request_from_csv(
                        request_id=function_args.get("request_id")
                    )
                    validation_result = function_response
                    
                    # Append tool execution result back to messages
                    messages_payload.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": json.dumps(function_response),
                    })
            
            # Second API call to get the final natural language answer
            second_response = openai_client.chat.completions.create(
                model=chat_deployment,
                messages=messages_payload,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "purchase_request_validation_response",
                        "strict": False,
                        "schema": validation_schema
                    }
                },
                temperature=0.3
            )
            model_message = second_response.choices[0].message.content
            try:
                model_result = json.loads(model_message)
            except (TypeError, json.JSONDecodeError):
                model_result = {}

            if validation_result and isinstance(model_result, dict):
                # Keep validation decisions from Python; use the model only for explanation formatting.
                for field_name in (
                    "pr_id",
                    "is_complete",
                    "required_approval_level",
                    "missing_fields",
                    "policy_violations",
                    "recommended_action",
                    "source",
                    "tool_used",
                ):
                    if field_name in validation_result:
                        model_result[field_name] = validation_result[field_name]
                final_message = json.dumps(model_result)
            else:
                final_message = json.dumps(validation_result) if validation_result else model_message
        else:
            final_message = response_message.content

        # Append final assistant reply to history and display it
        st.session_state.messages.append({"role": "assistant", "content": final_message})
        with st.chat_message("assistant"):
            render_assistant_response(final_message)
            
            # if retrieved_context:
            #     with st.expander("View Retrieved Documents & Sources (Context):"):
            #         st.text(retrieved_context)