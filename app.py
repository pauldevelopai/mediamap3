from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from models import db, User, MediaAnalysis, Chat, Message, Lesson, UserLesson, OrganizationInfo, OrganizationFact, Translation, TranslationFeedback, Location
import os
from openai import OpenAI
import json
from datetime import datetime, timezone
import urllib.parse
import requests
from auth import auth
import time
import threading
import uuid
import re

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

app.register_blueprint(auth)

# In-memory storage for active chats
active_chats = {}
last_save_time = {}
SAVE_INTERVAL = 60  # Save to database every 60 seconds

# Create a background thread for periodic saving
def periodic_save_chats():
    while True:
        with app.app_context():
            current_time = time.time()
            chats_to_save = []
            
            for chat_id, chat_data in active_chats.items():
                if chat_id not in last_save_time or (current_time - last_save_time[chat_id]) > SAVE_INTERVAL:
                    chats_to_save.append((chat_id, chat_data))
            
            for chat_id, chat_data in chats_to_save:
                save_chat_to_db(chat_id, chat_data)
                last_save_time[chat_id] = current_time
                
        time.sleep(SAVE_INTERVAL)

# Start the background thread
save_thread = threading.Thread(target=periodic_save_chats, daemon=True)
save_thread.start()

def save_chat_to_db(chat_id, chat_data):
    """Save or update a chat in the database"""
    try:
        # Fix the type error by ensuring chat_id is treated correctly
        # Convert chat_id to string first to check if it's a digit
        chat_id_str = str(chat_id)
        
        # Check if the chat already exists in the database
        chat = db.session.get(Chat, int(chat_id_str)) if chat_id_str.isdigit() else None
        
        if not chat:
            # Create a new chat if it doesn't exist
            chat = Chat()
            # Only add user_id if user is authenticated
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
                chat.user_id = current_user.id
            db.session.add(chat)
            db.session.flush()  # Get the ID
            
            # Update the chat_id in memory to match the database ID
            if chat_id in active_chats:
                active_chats[str(chat.id)] = active_chats.pop(chat_id)
                last_save_time[str(chat.id)] = last_save_time.pop(chat_id, time.time())
        
        # If there are messages, add them
        if 'messages' in chat_data:
            # Get existing message IDs
            existing_msg_ids = [msg.id for msg in chat.messages]
            
            for msg_data in chat_data['messages']:
                # Skip if this message is already in the database
                if 'id' in msg_data and msg_data['id'] in existing_msg_ids:
                    continue
                    
                msg = Message(
                    chat_id=chat.id,
                    role=msg_data['role'],
                    content=msg_data['content']
                )
                db.session.add(msg)
        
        # Generate a title if none exists
        if not chat.title and len(chat_data.get('messages', [])) > 0:
            first_msg = next((m for m in chat_data.get('messages', []) if m['role'] == 'user'), None)
            if first_msg:
                # Use the first 50 characters of the first user message as title
                chat.title = first_msg['content'][:50] + ("..." if len(first_msg['content']) > 50 else "")
        
        db.session.commit()
        return chat.id
    except Exception as e:
        db.session.rollback()
        print(f"Error saving chat to database: {e}")
        return None

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
def chat():
    message = request.json.get('message', '')
    chat_id = request.json.get('chat_id', None)
    
    if not message:
        return jsonify({
            'success': False,
            'error': 'No message provided'
        }), 400
    
    # Get or create a chat
    if chat_id:
        if chat_id in active_chats:
            chat_data = active_chats[chat_id]
        else:
            try:
                # Try to load from database
                chat = db.session.get(Chat, int(chat_id))
                if chat:
                    chat_data = {
                        'messages': [msg.to_dict() for msg in chat.messages]
                    }
                    active_chats[chat_id] = chat_data
                else:
                    active_chats[chat_id] = {'messages': []}
            except:
                active_chats[chat_id] = {'messages': []}
    else:
        # Generate a temporary ID for the new chat
        chat_id = str(uuid.uuid4())
        active_chats[chat_id] = {'messages': []}
    
    # Add user message
    active_chats[chat_id]['messages'].append({
        'role': 'user',
        'content': message
    })
    
    # Process with AI and get response - provide chat history for context
    response = process_with_ai(message, active_chats[chat_id]['messages'])
    
    # Add assistant response
    active_chats[chat_id]['messages'].append({
        'role': 'assistant',
        'content': response
    })
    
    # Schedule immediate save for this chat
    save_chat_to_db(chat_id, active_chats[chat_id])
    last_save_time[chat_id] = time.time()
    
    return jsonify({
        'success': True,
        'response': response,
        'chat_id': chat_id
    })

@app.route('/chats', methods=['GET'])
def get_chats():
    # Combine active chats with saved chats from the database
    chats = []
    
    # Get chats from database
    db_chats = Chat.query.order_by(Chat.updated_at.desc()).all()
    for chat in db_chats:
        chat_dict = chat.to_dict()
        # If this chat is active, use the in-memory version
        if str(chat.id) in active_chats:
            chat_dict['messages'] = active_chats[str(chat.id)]['messages']
        chats.append(chat_dict)
    
    # Add any active chats that aren't in the database yet
    for chat_id, chat_data in active_chats.items():
        if not chat_id.isdigit() or not any(c['id'] == int(chat_id) for c in chats):
            chats.append({
                'id': chat_id,
                'messages': chat_data['messages'],
                'created_at': datetime.now().isoformat()
            })
    
    return jsonify(chats)

def process_with_ai(message, chat_history=None):
    """Process user message with OpenAI and return response"""
    try:
        # Build the messages array for context
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_CHAT}
        ]
        
        # Add chat history for context if available
        if chat_history:
            for msg in chat_history:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        
        # Add the current user message
        messages.append({"role": "user", "content": message})
        
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages
        )
        
        # Extract and return the response text
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error processing with AI: {str(e)}")
        return f"Sorry, I encountered an error: {str(e)}"

@app.route('/synthesize', methods=['GET'])
def synthesize_org_info():
    """Synthesize information about the organization from available data"""
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    try:
        # Get organization info from the database
        org_info = OrganizationInfo.query.first()
        
        # If we're not refreshing and have existing data, return it
        if not refresh and org_info and org_info.org_info:
            return jsonify({
                'success': True,
                'org_info': json.loads(org_info.org_info) if org_info.org_info else {}
            })
        
        # Get all data that might be useful for synthesis
        chats = Chat.query.order_by(Chat.updated_at.desc()).limit(10).all()
        
        # Extract messages from chats
        messages = []
        for chat in chats:
            chat_messages = Message.query.filter_by(chat_id=chat.id).all()
            messages.extend([msg.content for msg in chat_messages])
        
        # If we don't have enough data, return a placeholder
        if not messages:
            default_info = {
                "Organization_Overview": "Paul Media",
                "Key_Projects": ["Project 1", "Project 2"],
                "Team_Members": ["Team Member 1", "Team Member 2"]
            }
            
            # Store this info in the database
            if not org_info:
                org_info = OrganizationInfo()
                db.session.add(org_info)
            
            org_info.org_info = json.dumps(default_info)
            org_info.updated_at = datetime.now(timezone.utc)  # Fix the deprecated warning
            db.session.commit()
            
            return jsonify({
                'success': True,
                'org_info': default_info
            })
        
        # Prepare content for analysis
        content = "\n".join(messages)
        
        # Send to OpenAI for analysis
        response = client.chat.completions.create(
            model="gpt-4", 
            messages=[
                {"role": "system", "content": "You are a helpful assistant that analyzes text and extracts information about an organization. Format your response as a JSON object with the following keys: Organization_Overview, Key_Projects, Team_Members. Each should contain relevant information extracted from the text."},
                {"role": "user", "content": f"Extract information about the organization from this text: {content}"}
            ]
        )
        
        # Extract and parse the JSON response
        json_text = response.choices[0].message.content.strip()
        
        # Try to handle common JSON formatting issues
        try:
            # First try to parse it directly
            org_data = json.loads(json_text)
        except json.JSONDecodeError:
            # If that fails, try to extract JSON from markdown code blocks or text
            json_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
            json_match = re.search(json_pattern, json_text)
            
            if json_match:
                try:
                    org_data = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    # If still failing, use a placeholder
                    org_data = {
                        "Organization_Overview": "Organization information could not be processed",
                        "Key_Projects": ["Unable to extract projects"],
                        "Team_Members": ["Unable to extract team members"]
                    }
            else:
                # Use default data if we can't parse JSON
                org_data = {
                    "Organization_Overview": "Paul Media",
                    "Key_Projects": ["Project 1", "Project 2"],
                    "Team_Members": ["Team Member 1", "Team Member 2"]
                }
        
        # Check if the JSON has the expected keys
        required_keys = ["Organization_Overview", "Key_Projects", "Team_Members"]
        for key in required_keys:
            if key not in org_data:
                org_data[key] = []
        
        # Store the result in the database
        if not org_info:
            org_info = OrganizationInfo()
            db.session.add(org_info)
        
        org_info.org_info = json.dumps(org_data)
        org_info.updated_at = datetime.now(timezone.utc)  # Fix the deprecated warning
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'org_info': org_data
        })
    
    except Exception as e:
        print(f"Error in synthesize_org_info: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
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

@app.route('/map')
@login_required
def show_map():
    return render_template('map.html')

@app.route('/api/user-locations')
@login_required
def get_user_locations():
    users = User.query.all()
    return jsonify({
        'users': [{
            'username': user.username,
            'latitude': user.latitude,
            'longitude': user.longitude,
            'location_name': user.location_name
        } for user in users if user.latitude and user.longitude]
    })

@app.route('/update-location', methods=['POST'])
@login_required
def update_location():
    data = request.json
    current_user.latitude = data.get('latitude')
    current_user.longitude = data.get('longitude')
    current_user.location_name = data.get('location_name')
    db.session.commit()
    return jsonify({'success': True})

@app.route('/add-fact', methods=['POST'])
@login_required
def add_fact():
    try:
        data = request.json
        fact_content = data.get('fact', '')
        
        # Store the fact
        new_fact = OrganizationFact(
            user_id=current_user.id,
            fact=fact_content
        )
        db.session.add(new_fact)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Fact added successfully"
        })
        
    except Exception as e:
        print(f"Error adding fact: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/analyze-chat', methods=['POST'])
@login_required
def analyze_chat():
    try:
        data = request.json
        message_content = data.get('message', '')
        
        # Get analysis from GPT-4
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": """You are a media analysis expert. 
                Analyze the given content and provide insights about:
                1. Key themes and topics
                2. Potential implications
                3. Recommendations
                Format your response in clear sections."""},
                {"role": "user", "content": message_content}
            ]
        )
        
        analysis = response.choices[0].message.content
        
        return jsonify({
            "success": True,
            "analysis": analysis
        })
        
    except Exception as e:
        print(f"Error generating analysis: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/translate', methods=['POST'])
@login_required
def translate_text():
    try:
        data = request.json
        text = data.get('text', '')
        target_language = data.get('target_language', '')
        
        # Get translation from GPT-4
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"You are a translator. Translate the following text to {target_language}. Only respond with the translation, no additional text."},
                {"role": "user", "content": text}
            ]
        )
        
        translated_text = response.choices[0].message.content
        
        # Store translation
        translation = Translation(
            user_id=current_user.id,
            original_text=text,
            translated_text=translated_text,
            source_language='auto',
            target_language=target_language
        )
        db.session.add(translation)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "translation": translated_text,
            "translation_id": translation.id
        })
        
    except Exception as e:
        print(f"Error in translation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/rate-translation', methods=['POST'])
@login_required
def rate_translation():
    try:
        data = request.json
        translation_id = data.get('translation_id')
        rating = data.get('rating')
        
        translation = Translation.query.get(translation_id)
        if translation and translation.user_id == current_user.id:
            translation.rating = rating
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": "Rating saved successfully"
            })
        
        return jsonify({
            "success": False,
            "error": "Translation not found"
        }), 404
        
    except Exception as e:
        print(f"Error rating translation: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/translate')
@login_required
def translate_page():
    return render_template('translate.html')

@app.route('/submit-correction', methods=['POST'])
@login_required
def submit_correction():
    try:
        data = request.json
        translation_id = data.get('translation_id')
        corrected_text = data.get('corrected_text')
        
        # Get original translation
        translation = Translation.query.get(translation_id)
        if translation and translation.user_id == current_user.id:
            # Store the correction
            feedback = TranslationFeedback(
                translation_id=translation_id,
                user_id=current_user.id,
                corrected_text=corrected_text,
                source_language=translation.source_language,
                target_language=translation.target_language
            )
            db.session.add(feedback)
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": "Correction saved successfully"
            })
        
        return jsonify({
            "success": False,
            "error": "Translation not found"
        }), 404
        
    except Exception as e:
        print(f"Error submitting correction: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/add-location', methods=['POST'])
@login_required
def add_location():
    try:
        data = request.json
        new_location = Location(
            user_id=current_user.id,
            name=data['name'],
            description=data.get('description', '')
        )
        db.session.add(new_location)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Location added successfully"
        })
        
    except Exception as e:
        print(f"Error adding location: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/get-locations')
@login_required
def get_locations():
    try:
        locations = Location.query.filter_by(user_id=current_user.id).all()
        return jsonify({
            "success": True,
            "locations": [{
                "name": loc.name,
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "description": loc.description
            } for loc in locations]
        })
        
    except Exception as e:
        print(f"Error getting locations: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/recommended-ai-tools')
@login_required
def recommended_ai_tools():
    return render_template('recommended_ai_tools.html')

@app.route('/generate-insights')
@login_required
def generate_insights():
    return render_template('generate_insights.html')

@app.route('/your-info')
def your_info():
    return render_template('your_info.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    # Admin dashboard logic here
    return render_template('admin_dashboard.html')

@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if request.method == 'POST':
        # In a real application, you would process the form data here
        # For example, save to database or send email to admin
        name = request.form.get('name')
        email = request.form.get('email')
        feedback_type = request.form.get('feedbackType')
        subject = request.form.get('subject')
        message = request.form.get('message')
        followup = 'followup' in request.form
        
        # Process the feedback (e.g., save to database, send email)
        # ...
        
        # For AJAX requests, return JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True})
        
        # For regular form submissions, redirect with a flash message
        flash('Thank you for your feedback!', 'success')
        return redirect(url_for('feedback'))
        
    # For GET requests, just render the template
    return render_template('feedback.html')

@app.route('/chat/<chat_id>', methods=['GET', 'DELETE'])
def manage_chat(chat_id):
    if request.method == 'GET':
        # Get a specific chat
        chat = Chat.query.get_or_404(int(chat_id))
        return jsonify(chat.to_dict())
    
    elif request.method == 'DELETE':
        # Delete a chat
        chat = Chat.query.get_or_404(int(chat_id))
        
        # Remove from active chats if present
        if str(chat_id) in active_chats:
            del active_chats[str(chat_id)]
        
        # Remove from database
        db.session.delete(chat)
        db.session.commit()
        
        return jsonify({'success': True})

@app.route('/chat-history')
def chat_history():
    return render_template('chats.html')

@app.route('/api/org-info', methods=['GET'])
def get_org_info():
    """Get organization info for the current user"""
    user_id = current_user.id if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated else None
    
    # Get organization facts for this user
    facts = []
    if user_id:
        org_facts = OrganizationFact.query.filter_by(user_id=user_id).all()
        facts = [fact.fact for fact in org_facts]
    
    # Get chat messages for analysis
    chat_messages = []
    if user_id:
        # Get the user's chats
        chats = Chat.query.filter_by(user_id=user_id).order_by(Chat.updated_at.desc()).limit(5).all()
        for chat in chats:
            messages = Message.query.filter_by(chat_id=chat.id).all()
            chat_messages.extend([msg.content for msg in messages])
    
    # If we don't have enough data, return a minimal placeholder
    if not chat_messages and not facts:
        return jsonify({
            "Organization_Overview": "No organization information available yet. Start chatting or add facts to build your profile.",
            "Key_Projects": [],
            "Team_Members": [],
            "Goals_Objectives": []
        })
    
    # Combine facts and messages for analysis
    content_to_analyze = "\n".join(facts + chat_messages)
    
    # Send to OpenAI for analysis
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_SYNTHESIS},
                {"role": "user", "content": content_to_analyze}
            ],
            max_tokens=1000
        )
        
        org_info_text = response.choices[0].message.content
        try:
            # Try to parse as JSON
            org_info = json.loads(org_info_text)
        except json.JSONDecodeError:
            # If not valid JSON, create a simplified structure
            org_info = {
                "Organization_Overview": org_info_text,
                "Key_Projects": [],
                "Team_Members": [],
                "Goals_Objectives": []
            }
        
        return jsonify(org_info)
        
    except Exception as e:
        print(f"Error analyzing organization info: {str(e)}")
        return jsonify({
            "error": "Could not analyze organization info",
            "Organization_Overview": "Error retrieving organization information.",
            "Key_Projects": [],
            "Team_Members": [],
            "Goals_Objectives": []
        }), 500

@app.cli.command("reset-db")
def reset_db():
    """Reset the database tables."""
    db_path = os.path.join(basedir, "instance", "media_analysis.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    with app.app_context():
        db.create_all()
    print("Database has been reset.")

# Create database tables
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True) 
