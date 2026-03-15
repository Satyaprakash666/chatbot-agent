from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os, random, json, base64
from pymongo import MongoClient
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from dotenv import load_dotenv
import os
import firebase_admin
from firebase_admin import credentials, auth
from groq import Groq
import pdfplumber
from transformers import AutoTokenizer, AutoModel
import torch
import torch.nn.functional as F
import faiss

app = Flask(__name__)
CORS(app)
load_dotenv()


MONGO_URI = os.environ.get("MONGO_URI") # changed
TOKEN_JSON = os.environ.get("GMAIL_TOKEN_JSON")
FIREBASE_ADMIN_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

SCOPES = ['https://www.googleapis.com/auth/gmail.send']


otp_storage = {}

ques_ans = {}
memory = {}

chunks = {}
sentence_embeddings = {}
faiss_index = {}
chk_max = {}

firebase_ready = False




client2 = MongoClient(MONGO_URI)
db = client2["chat_bot_database"]

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


if FIREBASE_ADMIN_JSON:
    try:
        service_account_info = json.loads(FIREBASE_ADMIN_JSON)
        fire_cred = credentials.Certificate(service_account_info)
        firebase_admin.initialize_app(fire_cred)
        firebase_ready = True
        print("✅ Firebase Admin connected.")
    except Exception as e:
        print(f"⚠️ Firebase initialization failed: {e}")
else:
    print("⚠️ Warning: FIREBASE_SERVICE_ACCOUNT not found. Auth features will be disabled.")




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

    
    memory[email] = ques_ans[email][-8:]

    memory[email].append({"role": "user", "content": user_input})
    ques_ans[email].append({"role": "user", "content": user_input})

    while True:
        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": 
                f"""
                    You are a Research Paper Analysis Assistant created by Satya Prakash. A PDF document has already been uploaded and processed, and its content is stored in a database as semantic embeddings. Whenever a user asks a question about the document, follow these steps:
                    1. Carefully read the user query. If the question is vague, general, or short, rewrite it into a detailed and precise version suitable for semantic search using the rewrite_question tool.
                    2. Perform semantic search in the database using the rewritten question. Choose the number of top relevant chunks (`top_k`) based on the complexity and specificity of the question:
                    - Use a smaller `top_k` for very specific questions (e.g., 3–5 chunks).
                    - Use a larger `top_k` for broad or general questions (e.g., up to {min(5, num_chunks)} chunks).
                    - If `top_k` is 0, assume the user has not uploaded a document yet.
                    3. Retrieve the most relevant chunks up to the chosen `top_k`.
                    4. Take the original user question along with the retrieved chunks as context and generate a clear, concise, and accurate answer directly with the main model. Ensure that all information is strictly grounded in the retrieved chunks, without hallucination or external content.
                    5. Present the answer in a structured, human-readable narrative format — **not in a table**. Do not list or cite chunk numbers explicitly. Instead, integrate information smoothly and naturally into the narrative.
                    6. 6. If user ask anything outside the document and research paper then dont respond anything and tell that i cant provied use me only for research paper related quries.  
                    7. Dont explictly tell the user that you cant respont anything else research paper.
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

        if msg.tool_calls:
            memory[email].append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": msg.tool_calls
            })
        else:
            memory[email].append({
                "role": "assistant",
                "content": msg.content or ""
            })

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

            memory[email].append({
                "role": "tool",
                "tool_call_id": tool.id,
                "name": tool_name,
                "content": result
            })


def get_gmail_service():
    if not TOKEN_JSON:
        raise Exception("GMAIL_TOKEN_JSON is missing in environment variables")
    
    creds_data = json.loads(TOKEN_JSON)
    creds = Credentials.from_authorized_user_info(creds_data, SCOPES)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            raise Exception("Refresh token invalid. Regenerate GMAIL_TOKEN_JSON.") from e
        
    if not creds.valid:
        raise Exception("Gmail credentials are invalid.")

    return build('gmail', 'v1', credentials=creds)



def send_otp(service, email, otp, name):
    subject = "Verify Your Chatbot Account - Your OTP Inside"
    body = f"""
<html>
<head>
<style>
    body {{
        font-family: 'Arial', sans-serif;
        color: #333;
        background-color: #f9f9f9;
        margin: 0;
        padding: 0;
    }}
    .container {{
        max-width: 600px;
        margin: 30px auto;
        background-color: #ffffff;
        padding: 30px;
        border-radius: 8px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }}
    h2 {{
        color: #1a1a1a;
        text-align: center;
        font-size: 28px;
        margin: 20px 0;
        letter-spacing: 1px;
    }}
    p {{
        font-size: 16px;
        line-height: 1.6;
    }}
    .otp-box {{
        background-color: #f1f5f9;
        padding: 15px;
        text-align: center;
        border-radius: 6px;
        font-weight: bold;
        font-size: 24px;
        letter-spacing: 2px;
        margin: 20px 0;
        color: #1a1a1a;
    }}
    .btn {{
        display: inline-block;
        background-color: #1a73e8;
        color: #ffffff !important;
        text-decoration: none;
        padding: 12px 24px;
        border-radius: 5px;
        font-weight: 600;
        margin-top: 20px;
    }}
    hr {{
        border: none;
        border-top: 1px solid #e0e0e0;
        margin: 30px 0;
    }}
    .footer {{
        font-size: 14px;
        color: #666666;
        text-align: center;
        margin-top: 20px;
    }}
</style>
</head>
<body>
    <div class="container">
        <p>Hello <strong>{name}</strong>,</p>

        <p>Thank you for signing up for our Chatbot service!<br>
        We're excited to have you on board.<br>
        To complete your registration and secure your account, please use the One-Time Password (OTP) below:</p>

        <div class="otp-box">{otp}</div>

        <p>This OTP is valid for <strong>5 minutes</strong>. Do not share it with anyone.<br>
        Enter it promptly to activate your account and start using all the features of the Chatbot.</p>

        <a href="#" class="btn">Verify Account</a>

        <hr>

        <p>If you did not sign up, you can safely ignore this email.</p>
        <hr>
        <div class="footer">
            <p>Need help? Contact us at: <strong>satyasp3466@gmail.com</strong></p>
            <p>Thank you,<br>
            <strong>Chatbot Security Team</strong><br>
            🌐 <a href="https://yourchatbotproject.com">Visit Chatbot</a></p>
        </div>
    </div>
</body>
</html>
"""
    
    message = MIMEText(body, "html")
    message['to'] = email
    message['subject'] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().messages().send(userId="me", body={'raw': raw}).execute()




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
    email = data.get('email')
    name = data.get('name')

    if not email:
        return jsonify({"error": "Email is required"}), 400

    try:
        is_user = auth.get_user_by_email(email)
        return jsonify({"error": "Email is already registered. Please login instead."}), 400
    except auth.UserNotFoundError:
        # Email not registered, continue
        pass
    except Exception as e:

        if "Malformed email address" in str(e):
            return jsonify({
                "error": "The email address format is incorrect. Please enter a valid email address.",
                "errorCode": "invalid-email"
            }), 400
        
        return jsonify({"error": e}), 500

    otp = str(random.randint(100000, 999999))

    try:
        service = get_gmail_service()  
        send_otp(service, email, otp, name)
        otp_storage[email.lower()] = otp

        return jsonify({"message": "✅ OTP sent successfully"}), 200
    except Exception as e:
        return jsonify({"error": "OTP could not be sent at the moment. Please try again later."}), 500
    

@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    data = request.get_json()
    email = data.get('email')
    otp = data.get('otp')
    if not email or not otp:
        return jsonify({"error": "Email and OTP required"}), 400
    stored_otp = otp_storage.get(email.lower())
    if otp == stored_otp:
        return jsonify({"message": "OTP verified"}), 200
    return jsonify({"error": "Invalid OTP"}), 400


@app.route('/register', methods=['POST'])
def register_user_with_otp():
    try:
        data = request.json
        email = data.get('email')
        name = data.get('name')
        password = data.get('password')
        otp = data.get('otp')

        if not all([email, name, password, otp]):
            return jsonify({"error": "All fields are required", "errorCode": "missing-fields"}), 400

        stored_otp = otp_storage.get(email.lower())
        if not stored_otp or str(otp).strip() != str(stored_otp).strip():
            return jsonify({"error": "OTP is invalid or expired", "errorCode": "invalid-otp"}), 400

        try:
            user_record = auth.create_user(
                email=email,
                password=password,
                display_name=name
            )
        except Exception as e:
            msg_lower = str(e).lower()
            error_code = "firebase-error"

            if "already exists" in msg_lower:
                error_code = "user-exists"
            elif "invalid email" in msg_lower:
                error_code = "invalid-email"
            elif "password must be a" in msg_lower or "weak password" in msg_lower:
                error_code = "weak-password"
            elif "operation not allowed" in msg_lower:
                error_code = "operation-not-allowed"
            print(str(e))

            return jsonify({"errorCode": error_code}), 400

        del otp_storage[email.lower()]
        store_resp = store_user(email=email, name=name)

        response = {
            "message": "User created successfully",
            "email": user_record.email,
            "name": user_record.display_name,
        }

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e), "errorCode": "server-error"}), 500


@app.route('/store_user', methods=['POST'])
def store_user(email=None, name=None):
    try:
        # If email and name are not provided as arguments, read from request.json
        if email is None or name is None:
            data = request.json
            email = data.get('email')
            name = data.get('name')

        if not email or not name:
            return jsonify({'error': 'Email and name are required'}), 400

        result = db.user.update_one(
            {'email': email},          # filter
            {'$set': {'name': name}},  # update
            upsert=True                # insert if not exists
        )

        if result.matched_count > 0:
            message = 'User updated successfully'
        else:
            message = 'User created successfully'

        return jsonify({'message': message}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/get_user', methods=['POST'])
def get_user():
    email = request.json.get('email')
    if not email:
            return jsonify({'error': 'Email is required'}), 400
    user = db.users.find_one({'email': email})
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

    pdf_path = os.path.join("uploads", f"{email}_{file.filename}")
    os.makedirs("uploads", exist_ok=True)
    file.save(pdf_path)
    try:
        create_chunks(pdf_path, email)
    except Exception as e:
        return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500
    
    return jsonify({"message": f"PDF uploaded and processed for {email}"}), 200


if __name__ == '__main__':
    app.run(port=10000)
