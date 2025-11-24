from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os, random, json, base64
from pymongo import MongoClient
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from dotenv import load_dotenv

from groq import Groq
import pdfplumber
from transformers import AutoTokenizer, AutoModel
import torch
import torch.nn.functional as F
import faiss


app = Flask(__name__)
CORS(app)
load_dotenv()

MONGO_URI = os.environ.get("MONGO_URI")
TOKEN_JSON = os.environ.get("GMAIL_TOKEN_JSON")
SCOPES = ['https://www.googleapis.com/auth/gmail.send']


client_db = MongoClient(MONGO_URI)
db = client_db['help_for_farmer']

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


otp_storage = {}

ques_ans = {}
memory = {}

chunks = {}
sentence_embeddings = {}
faiss_index = {}
chk_max = {}


model = AutoModel.from_pretrained('sentence-transformers/all-MiniLM-L6-v2')
tokenizer = AutoTokenizer.from_pretrained('sentence-transformers/all-MiniLM-L6-v2')


def mean_pooling(model_output, attention_mask):
    token_embeddings = model_output[0]
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)

def create_chunks(pdf_path, email):
    global chunks, sentence_embeddings, faiss_index, chk_max

    chunks[email] = []
    sentence_embeddings[email] = None
    faiss_index[email] = None

    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""

    words = text.split()
    max_words = 150
    for i in range(0, len(words), max_words):
        chunk = " ".join(words[i:i+max_words])
        chunks[email].append(chunk)

    encoded_input = tokenizer(chunks[email], padding=True, truncation=True, return_tensors='pt')
    with torch.no_grad():
        model_output = model(**encoded_input)

    sentence_embeddings[email] = mean_pooling(model_output, encoded_input['attention_mask'])
    sentence_embeddings[email] = F.normalize(sentence_embeddings[email], p=2, dim=1)
    chk_max[email] = len(sentence_embeddings[email])

    embeddings_np = sentence_embeddings[email].cpu().numpy().astype('float32')
    dimension = embeddings_np.shape[1]
    faiss_index[email] = faiss.IndexFlatL2(dimension)
    faiss_index[email].add(embeddings_np)
    print(f"FAISS index built with {faiss_index[email].ntotal} vectors for {email}")
    

# Tools 
def list_of_char():
    return "Hii, I am List of char function"

def budget(month=None):
    if month=="july":
        return "₹15000"
    elif month=="august":
        return "₹8000"
    elif month=="september":
        return "₹12000"
    return "₹0"

def rewrite_question(question):
    chat = client.chat.completions.create(
        messages=[
            {"role": "system", "content": "You are a helpful assistant. Rewrite user question into detailed form for semantic search."},
            {"role": "user", "content": question},
        ],
        model="openai/gpt-oss-120b",
        tools=[],
        stream=False
    )
    return chat.choices[0].message.content

def semantic_search(searching_query, top_k=3, email=None):
    global chunks, faiss_index, model, tokenizer

    if email not in faiss_index or faiss_index[email] is None:
        return []

    encoded_query = tokenizer(searching_query, padding=True, truncation=True, return_tensors='pt')
    with torch.no_grad():
        query_output = model(**encoded_query)

    query_embedding = mean_pooling(query_output, encoded_query['attention_mask'])
    query_embedding = F.normalize(query_embedding, p=2, dim=1)
    query_np = query_embedding.cpu().numpy().astype('float32')

    distances, indices = faiss_index[email].search(query_np, top_k)
    results = []
    for rank, idx in enumerate(indices[0]):
        results.append({
            "rank": str(rank + 1),
            "score": str(distances[0][rank]),
            "chunk": chunks[email][idx]
        })
    return results


def call_agent(user_input, email):
    global memory, ques_ans, chk_max

    if email not in memory:
        memory[email] = []
    if email not in ques_ans:
        ques_ans[email] = []

    num_chunks = chk_max.get(email, 0)
    # print(f"------------------------------------------- {num_chunks}")

    # Add last few messages to memory
    # if len(ques_ans[email]) >= 4:
    #     memory[email].extend(ques_ans[email][-4:])
    if len(ques_ans[email]) >= 2:
        memory[email].extend(ques_ans[email][-2:])

    memory[email].append({"role": "user", "content": user_input})
    ques_ans[email].append({"role": "user", "content": user_input})

    while True:
        chat = client.chat.completions.create(
            messages=[
                # {"role": "system", "content": "You are a research paper analysis assistant. you already have the document uploaded and processed. You have following tools to use : 1. budget - to get the remaining balance in the bank account , 2. rewrite_question - to rewrite user question into a detailed for better semantic-search , 3. semantic_search - to perform semantic search using FAISS , 4. answer_ques - to answer user question based on the retrieved context from semantic search ."},
                {"role": "system", "content": 
                # f"""You are a Research Paper Analysis Assistant. A PDF document has already been uploaded and processed, and its content is stored in a database as semantic embeddings. Whenever a user asks a question about the document, first carefully read the query and, if it is vague or general, rewrite it into a detailed and precise version suitable for semantic search using the rewrite_question tool. Use this rewritten question to perform a semantic search in the database and retrieve the most relevant chunks, up to a maximum of {str(min(10, chk_max))}, using the semantic_search tool. Then, take the original user question along with the retrieved chunks as context and generate a clear, concise, and accurate answer directly with the main model, ensuring that all information is grounded strictly in the retrieved chunks without hallucination or adding external content. Present the answer in a structured, professional, and human-readable format, combining multiple relevant chunks logically if needed, and indicate references or source chunks where appropriate. Always follow this process: rewrite the question, perform semantic search, and answer based on the retrieved content."""},
                f"""
                    You are a Research Paper Analysis Assistant. A PDF document has already been uploaded and processed, and its content is stored in a database as semantic embeddings. Whenever a user asks a question about the document, follow these steps:

                    1. Carefully read the user query. If the question is vague, general, or short, rewrite it into a detailed and precise version suitable for semantic search using the rewrite_question tool.

                    2. Perform semantic search in the database using the rewritten question. Choose the number of top relevant chunks (`top_k`) based on the complexity and specificity of the question:
                    - Use a smaller `top_k` for very specific questions (e.g., 3–5 chunks).
                    - Use a larger `top_k` for broad or general questions (e.g., up to {min(5, num_chunks)} chunks).
                    - If `top_k` is 0, assume the user has not uploaded a document yet.

                    3. Retrieve the most relevant chunks up to the chosen `top_k`.

                    4. Take the original user question along with the retrieved chunks as context and generate a clear, concise, and accurate answer directly with the main model. Ensure that all information is strictly grounded in the retrieved chunks, without hallucination or external content.

                    5. Present the answer in a structured, human-readable narrative format — **not in a table**. Do not list or cite chunk numbers explicitly. Instead, integrate information smoothly and naturally into the narrative.

                    6. If user ask anything outside the document and research paper then dont respond anything and tell that i cant provied use me only for research paper related quries.  

                    Always follow this process: rewrite the question → semantic search → answer based on retrieved content (no chunk references, no table format).
                    """},
                
                *memory[email]
            ],
            model="openai/gpt-oss-120b",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "budget",
                        "description": "return how much i spend in given month",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "month": {
                                    "type": "string",
                                    "description": "full name of month in small letters"
                                }
                            },
                            "required": ["month"]},
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "rewrite_question",
                        "description": "Rewrite user question into a detailed for better semantic-search",
                        "parameters": {
                            "type": "object", 
                            "properties": {
                                "question": {
                                    "type": "string", 
                                    "description":"this is the original question ask by the user"
                                }
                            }, "required": ["question"]
                        },
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "semantic_search",
                        "description": "Performs a semantic search on the document embeddings using FAISS. This function takes the rewritten, detailed question produced by the `rewrite_question` tool and retrieves the most relevant chunks of text.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "rewritten_question": {
                                    "type": "string",
                                    "description": "The detailed semantic-search query generated from the user's original question using the `rewrite_question` tool."
                                },
                                "top_k": {
                                    "type": "integer",
                                    "description": "The number of top similar chunks to retrieve from the document embeddings."
                                }
                            },
                            "required": ["rewritten_question", "top_k"]
                        }
                    }
                }

            ],
            stream=False
        )
        msg = chat.choices[0].message
        memory[email].append(msg)

        if not msg.tool_calls:
            ques_ans[email].append({"role": "assistant", "content": msg.content})
            return msg.content

        for tool in msg.tool_calls:
            tool_name = tool.function.name
            tool_args = json.loads(tool.function.arguments)
            result = None

            if tool_name == "list_of_char":
                result = list_of_char()
            elif tool_name == "budget":
                result = budget(tool_args.get("month"))
            elif tool_name == "rewrite_question":
                result = rewrite_question(tool_args.get("question",""))
            elif tool_name == "semantic_search":
                result = semantic_search(tool_args.get("rewritten_question",""), tool_args.get("top_k",3), email)
                result = json.dumps(result)
            else:
                result = f"Unknown tool: {tool_name}"

            memory[email].append({"role": "tool","content": result,"tool_call_id": tool.id})



# ----------------- Gmail -----------------
def get_gmail_service():
    creds = None
    if TOKEN_JSON:
        creds = Credentials.from_authorized_user_info(json.loads(TOKEN_JSON), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    
    service = build('gmail', 'v1', credentials=creds)
    return service

def send_otp(service, email, otp, name):
    subject = "Your Chatbot OTP Verification"
    body = f"""
    <p>Hello {name},</p>
    <p>Thank you for using our Chatbot service. Your OTP for verification is: <strong>{otp}</strong></p>
    <p>Please enter this OTP to continue your chat session.</p>
    <p>— Team ChatBot </p>
    """
    message = MIMEText(body, "html")
    message['to'] = email
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().messages().send(userId="me", body={'raw': raw}).execute()


# ----------------- Routes -----------------
@app.route('/')
@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/home')
def index():
    return render_template('chat.html') 

@app.route('/send-otp', methods=['POST'])
def send_otp_route():
    data = request.get_json()
    email, name = data.get('email'), data.get('name')
    if not email or not name:
        return jsonify({"error": "Name and Email are required"}), 400
    otp = str(random.randint(100000, 999999))
    otp_storage[email] = otp
    send_otp(get_gmail_service(), email, otp, name)
    return jsonify({"message": "OTP sent successfully"})

@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    data = request.get_json()
    email, otp = data.get('email'), data.get('otp')
    if otp_storage.get(email) == otp:
        del otp_storage[email]
        return jsonify({"message": "OTP verified"}), 200
    return jsonify({"error": "Invalid OTP"}), 400

@app.route('/store_user', methods=['POST'])
def store_user():
    data = request.json
    email, name = data.get('email'), data.get('name')
    if not email or not name:
        return jsonify({'error': 'Email and name required'}), 400
    if db.user.find_one({'email': email}):
        return jsonify({'error': 'User already exists'}), 400
    db.user.insert_one({'email': email, 'name': name})
    return jsonify({'message': 'User stored successfully'}), 200

@app.route('/get_user', methods=['POST'])
def get_user():
    email = request.json.get('email')
    user = db.user.find_one({'email': email})
    if user:
        return jsonify({'name': user['name'], 'email': user['email']}), 200
    return jsonify({'error': 'User not found'}), 404

@app.route('/close', methods=['POST'])
def close_chat():
    email = request.json.get('email')
    if email:
        memory[email] = []
        ques_ans[email] = []
        chunks[email] = []
        sentence_embeddings[email] = None
        faiss_index[email] = None
        chk_max[email] = 0

        return jsonify({"message": f"Memory for {email} cleared"}), 200
    return jsonify({"error": "Email required"}), 400

@app.route('/ask', methods=['POST'])
def ask_question():
    data = request.json
    email = data.get('email')
    question = data.get('question')

    if not email or not question:
        return jsonify({"error": "Email and question required"}), 400

    try:
        result = call_agent(question, email)
        response = ques_ans[email][-1]['content'] if ques_ans[email] else "No response"
    except Exception as e:
        print("Error in call_agent:", e)
        response = f"AI could not generate a response: {str(e)}"
    
    return jsonify({"response": response}), 200

@app.route('/pdf', methods=['POST'])
def upload_pdf():
    email = request.form.get('email')
    file = request.files.get('file')
    if not email or not file:
        return jsonify({"error": "Email and PDF file required"}), 400

    # Use /tmp for temporary storage
    tmp_path = os.path.join("/tmp", f"{email}_{file.filename}")
    file.save(tmp_path)

    try:
        create_chunks(tmp_path, email)
    except Exception as e:
        return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500
    
    return jsonify({"message": f"PDF uploaded and processed for {email}"}), 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Use Render’s assigned port
    app.run(host='0.0.0.0', port=port, threaded=False)




