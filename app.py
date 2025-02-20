from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from models import db, User, MediaAnalysis, Chat, Message
import os
from openai import OpenAI

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')

# Create instance directory if it doesn't exist
os.makedirs('instance', exist_ok=True)

# Use absolute path for database
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "instance", "media_analysis.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

SYSTEM_PROMPT_ANALYSIS = """You are an expert media analyst with deep knowledge of content analysis, 
cultural context, and media trends. When analyzing media:
1. Examine the content's key themes and messages
2. Identify the target audience and intended impact
3. Evaluate the technical and creative execution
4. Consider cultural and social implications
5. Provide constructive insights and recommendations

Format your analysis in clear sections with bullet points where appropriate."""

SYSTEM_PROMPT_CHAT = """You are an expert media analysis assistant with deep knowledge of:
- Content creation and strategy
- Digital media trends
- Social media platforms
- Video and image analysis
- Content marketing
- Audience engagement

Provide clear, actionable insights and always maintain context from previous messages.
When appropriate, break down your responses into organized sections for better readability."""

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('home'))
        
    return render_template('login.html')

@app.route('/')
@login_required
def home():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
@login_required
def analyze_media():
    try:
        data = request.json
        media_url = data.get('media_url')
        
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_ANALYSIS},
                {"role": "user", "content": f"""Please analyze this media content: {media_url}

                Consider:
                - Content quality and originality
                - Visual/audio elements (if applicable)
                - Engagement potential
                - Target audience fit
                - Areas for improvement"""}
            ]
        )
        
        analysis = response.choices[0].message.content
        
        # Save to database
        media_analysis = MediaAnalysis(
            media_url=media_url,
            analysis_result=analysis,
            user_id=current_user.id
        )
        db.session.add(media_analysis)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "analysis": analysis
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    try:
        data = request.json
        user_message = data.get('message')
        chat_id = data.get('chat_id')
        
        # Get or create chat
        if not chat_id:
            chat = Chat(user_id=current_user.id)
            db.session.add(chat)
            db.session.commit()
            chat_id = chat.id
        else:
            chat = Chat.query.get(chat_id)
            if not chat or chat.user_id != current_user.id:
                raise ValueError("Invalid chat ID")
        
        # Save user message
        user_msg = Message(
            chat_id=chat_id,
            role='user',
            content=user_message
        )
        db.session.add(user_msg)
        
        # Prepare messages for OpenAI
        chat_messages = [{"role": msg.role, "content": msg.content} 
                        for msg in chat.messages]
        chat_messages.insert(0, {
            "role": "system",
            "content": SYSTEM_PROMPT_CHAT
        })
        
        # Get AI response
        response = client.chat.completions.create(
            model="gpt-4",
            messages=chat_messages
        )
        
        ai_response = response.choices[0].message.content
        
        # Save AI response
        ai_msg = Message(
            chat_id=chat_id,
            role='assistant',
            content=ai_response
        )
        db.session.add(ai_msg)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "response": ai_response,
            "chat_id": chat_id
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/chats')
@login_required
def get_chats():
    chats = Chat.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': chat.id,
        'created_at': chat.created_at,
        'messages': [{
            'role': msg.role,
            'content': msg.content,
            'created_at': msg.created_at
        } for msg in chat.messages]
    } for chat in chats])

# Create database tables
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True) 