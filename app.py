from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from models import db, User, MediaAnalysis, Chat, Message, Lesson, UserLesson, OrganizationInfo
import os
from openai import OpenAI
import json
from datetime import datetime

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

SYSTEM_PROMPT_SYNTHESIS = """You are an organizational analyst. Extract key information about the organization from the conversation and categorize it into:
1. Organization Overview
2. Key Projects
3. Team Members
4. Goals & Objectives
5. Resources & Tools

Return the information in JSON format with these categories. Only include information that has been explicitly mentioned or can be directly inferred."""

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

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

@app.route('/synthesize', methods=['GET'])
@login_required
def synthesize_org_info():
    try:
        # Check if we should refresh
        should_refresh = request.args.get('refresh', 'false') == 'true'
        
        # Try to get existing org info
        org_info = OrganizationInfo.query.filter_by(user_id=current_user.id).first()
        
        # Return existing info if it exists and we're not refreshing
        if org_info and not should_refresh:
            return jsonify({
                "success": True,
                "org_info": {
                    "Organization_Overview": org_info.overview,
                    "Key_Projects": json.loads(org_info.key_projects or '[]'),
                    "Team_Members": json.loads(org_info.team_members or '[]'),
                    "Goals_Objectives": json.loads(org_info.goals or '[]'),
                    "Resources_Tools": json.loads(org_info.resources or '[]')
                }
            })
        
        # Get all chats for the current user
        chats = Chat.query.filter_by(user_id=current_user.id).all()
        
        # Compile all messages into a conversation history
        conversation_history = []
        for chat in chats:
            for message in chat.messages:
                conversation_history.append(f"{message.role}: {message.content}")
        
        if not conversation_history:
            default_info = {
                "Organization_Overview": "No information available yet",
                "Key_Projects": [],
                "Team_Members": [],
                "Goals_Objectives": [],
                "Resources_Tools": []
            }
            return jsonify({"success": True, "org_info": default_info})
        
        # Get synthesis from OpenAI
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": """You are an organizational analyst. Extract key information about the organization from the conversation and return it in this exact JSON format:
{
    "Organization_Overview": "Brief overview text",
    "Key_Projects": ["project1", "project2", ...],
    "Team_Members": ["member1", "member2", ...],
    "Goals_Objectives": ["goal1", "goal2", ...],
    "Resources_Tools": ["resource1", "resource2", ...]
}
Only include information that has been explicitly mentioned or can be directly inferred."""},
                {"role": "user", "content": "\n".join(conversation_history)}
            ]
        )
        
        # Parse the response
        synthesis = json.loads(response.choices[0].message.content)
        
        # Update or create org info in database
        if not org_info:
            org_info = OrganizationInfo(user_id=current_user.id)
            db.session.add(org_info)
        
        org_info.overview = synthesis["Organization_Overview"]
        org_info.key_projects = json.dumps(synthesis["Key_Projects"])
        org_info.team_members = json.dumps(synthesis["Team_Members"])
        org_info.goals = json.dumps(synthesis["Goals_Objectives"])
        org_info.resources = json.dumps(synthesis["Resources_Tools"])
        org_info.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "org_info": synthesis
        })
        
    except Exception as e:
        print(f"Error in synthesize_org_info: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/lessons')
@login_required
def get_lessons():
    try:
        # Get user's lesson progress
        user_lessons = UserLesson.query.filter_by(user_id=current_user.id).all()
        completed_lessons = {ul.lesson_id for ul in user_lessons if ul.completed}
        
        # Get current lesson or next available
        current_lesson = Lesson.query.filter(
            ~Lesson.id.in_(completed_lessons)
        ).order_by(Lesson.order).first()
        
        if not current_lesson:
            # Generate new lesson using OpenAI
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": """You are an AI workflow expert creating a lesson plan.
                    Create a lesson about implementing AI in workflows. Include:
                    1. A clear title
                    2. The main lesson content with practical examples
                    3. An exercise for practice
                    4. Key takeaways
                    Format in markdown."""},
                    {"role": "user", "content": "Generate a new lesson about AI workflows"}
                ]
            )
            
            lesson_content = response.choices[0].message.content
            
            # Create new lesson
            new_lesson = Lesson(
                title=f"Lesson {Lesson.query.count() + 1}",
                content=lesson_content,
                order=Lesson.query.count() + 1
            )
            db.session.add(new_lesson)
            db.session.commit()
            
            current_lesson = new_lesson
        
        return jsonify({
            "success": True,
            "lesson": {
                "id": current_lesson.id,
                "title": current_lesson.title,
                "content": current_lesson.content,
                "completed": current_lesson.id in completed_lessons
            }
        })
        
    except Exception as e:
        print(f"Error in get_lessons: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/lessons/complete/<int:lesson_id>', methods=['POST'])
@login_required
def complete_lesson(lesson_id):
    try:
        user_lesson = UserLesson.query.filter_by(
            user_id=current_user.id,
            lesson_id=lesson_id
        ).first()
        
        if not user_lesson:
            user_lesson = UserLesson(
                user_id=current_user.id,
                lesson_id=lesson_id
            )
            db.session.add(user_lesson)
        
        user_lesson.completed = True
        user_lesson.last_accessed = datetime.utcnow()
        db.session.commit()
        
        return jsonify({"success": True})
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/lessons-page')
@login_required
def lessons_page():
    return render_template('lessons.html')

@app.route('/lessons/create', methods=['POST'])
@login_required
def create_new_lesson():
    try:
        # Generate new lesson using OpenAI
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": """You are an AI workflow expert creating a lesson plan.
                Create a lesson about implementing AI in workflows. Include:
                1. A clear title
                2. The main lesson content with practical examples
                3. An exercise for practice
                4. Key takeaways
                Format in markdown."""},
                {"role": "user", "content": "Generate a new lesson about AI workflows"}
            ]
        )
        
        lesson_content = response.choices[0].message.content
        
        # Create new lesson
        new_lesson = Lesson(
            title=f"Lesson {Lesson.query.count() + 1}",
            content=lesson_content,
            order=Lesson.query.count() + 1
        )
        db.session.add(new_lesson)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "lesson": {
                "id": new_lesson.id,
                "title": new_lesson.title,
                "content": new_lesson.content
            }
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# Create database tables
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5001) 