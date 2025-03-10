from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, Blueprint, abort
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
from urllib.parse import urlparse
import io
import traceback
import sys
from functools import wraps
from sqlalchemy import Column, Boolean, text
from sqlalchemy.exc import OperationalError

# Create the ai_utility blueprint
ai_utility_bp = Blueprint('ai_utility', __name__, url_prefix='/ai-utility')

# Define routes for the ai_utility blueprint
@ai_utility_bp.route('/')
def index():
    """AI Utility home page"""
    return render_template('ai_utility.html')

@ai_utility_bp.route('/dashboard')
def dashboard():
    """AI Utility dashboard page"""
    return render_template('ai_utility_dashboard.html')

@ai_utility_bp.route('/analytics')
def analytics():
    """AI Utility analytics page"""
    return render_template('ai_utility_analytics.html')

# Create the metadata blueprint
metadata_bp = Blueprint('metadata', __name__, url_prefix='/metadata')

# Define routes for the metadata blueprint
@metadata_bp.route('/')
def home():
    """Metadata home page"""
    return render_template('metadata_home.html')

@metadata_bp.route('/add')
def add():
    """Add metadata page"""
    return render_template('add_metadata.html')

@metadata_bp.route('/add', methods=['POST'])
def add_post():
    """Process metadata form submission"""
    data = request.json
    # Process the metadata data here
    return jsonify({'success': True, 'message': 'Metadata added successfully'})

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
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = None  # This will disable the message entirely

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
app.register_blueprint(ai_utility_bp)
app.register_blueprint(metadata_bp)

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

@app.route('/')
def index():
    # Redirect to login page directly
    return redirect(url_for('login'))

@app.route('/landing-page-1')
def landing_page1():
    # Content & Development Suite
    return render_template('landing_page1.html')

@app.route('/landing-page-2')
def landing_page2():
    # Security & Justice Suite
    return render_template('landing_page2.html')

@app.route('/select_platform/<platform>')
def select_platform(platform):
    session['platform'] = platform
    
    if platform == 'mediamap' or platform == 'implement_ai':
        return redirect(url_for('mediamap_home'))
    elif platform == 'language':
        return redirect(url_for('translate_page'))
    elif platform == 'ai_utility' or platform == 'contentflow':
        return redirect(url_for('ai_utility.index'))
    elif platform == 'training':
        return redirect(url_for('training_lab'))
    elif platform == 'store':
        return redirect(url_for('ai_store'))
    else:
        flash('Invalid platform selection.', 'danger')
        return redirect(url_for('landing_page1'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login route that redirects to landing_page1 after successful login"""
    if current_user.is_authenticated:
        # Check if user is admin and redirect accordingly
        if hasattr(current_user, 'is_admin') and current_user.is_admin:
            return redirect(url_for('admin_dashboard'))
        # Redirect to landing_page1 if already logged in
        return redirect(url_for('landing_page1'))
    
    # Handle login form submission
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        # Check if the user exists
        if user:
            # We need to determine which attribute stores the password
            # Let's try the common attribute names
            password_verified = False
            
            # Inspect the user object to find potential password fields
            user_dict = user.__dict__
            password_field = None
            
            # List of potential password field names
            potential_fields = ['password_hash', 'hashed_password', 'pwd', 'pwd_hash', 'password_digest']
            
            for field in potential_fields:
                if field in user_dict:
                    password_field = field
                    break
            
            # If we found a password field, verify the password
            if password_field and check_password_hash(getattr(user, password_field), password):
                login_user(user)
                
                # Update last login time
                user.last_login = datetime.utcnow()
                db.session.commit()
                
                # Check if user is admin and redirect accordingly
                if hasattr(user, 'is_admin') and user.is_admin:
                    return redirect(url_for('admin_dashboard'))
                
                # Redirect to landing_page1 after successful login
                return redirect(url_for('landing_page1'))
            else:
                # If no proper password field was found or password didn't match
                flash('Invalid username or password.', 'danger')
        else:
            flash('Invalid username or password.', 'danger')
    
    # Render the login template
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logout and clear platform selection"""
    logout_user()
    session.pop('platform', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# Platform-specific routes with access control
@app.route('/mediamap')
@login_required
def mediamap_home():
    """Implement AI home page"""
    session['platform'] = 'implement_ai'
    
    # Get organization info from the synthesize_org_info function
    response = synthesize_org_info()
    org_info = response.get_json() if hasattr(response, 'get_json') else None
    
    return render_template('mediamap_home.html', active_page='dashboard', org_info=org_info)

@app.route('/ai-utility')
@login_required
def ai_utility():
    """AI Utility home page"""
    # Set the platform in session
    session['platform'] = 'ai_utility'
    # Render the complete ai_utility template
    return render_template('ai_utility.html', hide_right_sidebar=True)

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
                # Try to load from database - ensure it belongs to current user
                chat = db.session.get(Chat, int(chat_id))
                if chat and chat.user_id == current_user.id:
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

@app.route('/chats')
@login_required
def get_chats():
    """Render the chat history page"""
    return render_template('chats.html')

@app.route('/api/user_chats')
@login_required
def api_user_chats():
    """API endpoint to get user's chat history"""
    # Get chats from database
    chats = Chat.query.filter_by(user_id=current_user.id).order_by(Chat.created_at.desc()).all()
    
    # Convert to JSON
    chats_json = []
    for chat in chats:
        messages = [
            {
                'id': msg.id,
                'role': msg.role,
                'content': msg.content,
                'created_at': msg.created_at.isoformat()
            } for msg in chat.messages
        ]
        
        chats_json.append({
            'id': chat.id,
            'title': chat.title,
            'created_at': chat.created_at.isoformat(),
            'updated_at': chat.updated_at.isoformat(),
            'messages': messages
        })
    
    return jsonify(chats_json)

@app.route('/chat/<int:chat_id>', methods=['GET'])
@login_required
def get_chat(chat_id):
    """Get a specific chat"""
    chat = Chat.query.filter_by(id=chat_id, user_id=current_user.id).first_or_404()
    
    # Convert to JSON
    messages = [
        {
            'id': msg.id,
            'role': msg.role,
            'content': msg.content,
            'created_at': msg.created_at.isoformat()
        } for msg in chat.messages
    ]
    
    chat_json = {
        'id': chat.id,
        'title': chat.title,
        'created_at': chat.created_at.isoformat(),
        'updated_at': chat.updated_at.isoformat(),
        'messages': messages
    }
    
    return jsonify(chat_json)

@app.route('/chat/<int:chat_id>', methods=['DELETE'])
@login_required
def delete_chat(chat_id):
    """Delete a specific chat"""
    chat = Chat.query.filter_by(id=chat_id, user_id=current_user.id).first_or_404()
    
    try:
        db.session.delete(chat)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

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

def get_current_user_id():
    """Safely get current user ID with logging"""
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        logger.info(f"Authenticated user: {current_user.id} ({current_user.username})")
        return current_user.id
    logger.info("No authenticated user")
    return None

@app.route('/synthesize')
def synthesize_org_info():
    """Synthesize information about the organization from available data"""
    refresh = request.args.get('refresh', 'false').lower() == 'true'
    print(f"Synthesize called with refresh={refresh} for user={current_user.username if hasattr(current_user, 'username') else 'anonymous'}")
    
    # Get current user id safely
    user_id = current_user.id if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated else None
    
    # Generic response for non-authenticated users
    if not user_id:
        return jsonify({
            'success': True,
            'org_info': {
                "Organization_Overview": "Please log in to view your organization",
                "Key_Projects": ["Login required"],
                "Team_Members": ["Login required"]
            }
        })
    
    try:
        # Always analyze chats when refresh is requested
        if refresh:
            print(f"⭐ Forced refresh requested - analyzing chats for {current_user.username}")
            
            # Get user's chats with explicit filtering
            chats = Chat.query.filter_by(user_id=user_id).order_by(Chat.updated_at.desc()).limit(10).all()
            print(f"Found {len(chats)} chats for user {current_user.username}")
            
            # Extract messages
            messages = []
            for chat in chats:
                chat_messages = Message.query.filter_by(chat_id=chat.id).all()
                messages.extend([msg.content for msg in chat_messages])
            
            print(f"Extracted {len(messages)} messages for user {current_user.username}")
            
            # Prepare default info
            username = current_user.username
            default_info = {
                "Organization_Overview": f"{username}'s Organization",
                "Key_Projects": ["No projects yet"],
                "Team_Members": [f"{username}"]
            }
            
            # If we have messages, analyze them
            if messages:
                content = "\n".join(messages)
                
                # Updated regex patterns to be more precise
                org_patterns = [
                    # Pattern for "company/organization name/called/is: NAME"
                    r"(?:company|organization|organisation|business|firm|agency)\s+(?:name|called|is|:)\s+([A-Za-z0-9][A-Za-z0-9\s&'-]+)",
                    # Pattern for "I work at NAME"
                    r"(?:I work|I'm working|I am working|employed|work)\s+(?:at|for|with)\s+([A-Za-z0-9][A-Za-z0-9\s&'-]+)",
                    # Pattern for "NAME is my company"
                    r"([A-Za-z0-9][A-Za-z0-9\s&'-]+)\s+(?:is my|is our|is the)\s+(?:company|organization|organisation|business|employer)"
                ]
                
                # Try to directly extract company name
                org_name = None
                for pattern in org_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        for match in matches:
                            # Clean up the matched name
                            potential_name = match.strip()
                            
                            # More aggressive cleanup to remove prefix words like "called"
                            prefixes_to_remove = ["called", "named", "is", "the"]
                            for prefix in prefixes_to_remove:
                                if potential_name.lower().startswith(prefix + " "):
                                    potential_name = potential_name[len(prefix)+1:].strip()
                            
                            # Remove common noise words at the end
                            noise_words = ['that', 'which', 'and', 'is', 'a', 'an', 'the', 'called', 'named']
                            for word in noise_words:
                                if potential_name.lower().endswith(f" {word}"):
                                    potential_name = potential_name[:-len(word)-1].strip()
                            
                            # Also remove trailing punctuation
                            potential_name = re.sub(r'[.,;:!?]+$', '', potential_name).strip()
                            
                            # For names like "called TOTAL MEDIA", extract just "TOTAL MEDIA"
                            if "called " in potential_name.lower():
                                potential_name = potential_name.lower().split("called ")[1].strip().upper()
                            
                            if len(potential_name) > 3:  # Avoid short meaningless matches
                                org_name = potential_name
                                print(f"🔍 Direct regex match found organization: '{org_name}'")
                                break
                    
                    if org_name:
                        break
                
                # Also try to find project names
                project_patterns = [
                    r"(?:project|initiative|campaign) (?:called|named|titled) ([A-Za-z0-9\s&'-]+?)(?:\.|\band\b|\bthat\b|\bwhich\b|\,|\;|$)",
                    r"working on ([A-Za-z0-9\s&'-]+?) (?:project|initiative|campaign)"
                ]
                
                projects = []
                for pattern in project_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    for match in matches:
                        project = match.strip()
                        if len(project) > 3 and project not in projects:
                            projects.append(project)
                
                if org_name:
                    # If we found a direct mention, use it
                    default_info["Organization_Overview"] = org_name
                
                if projects:
                    default_info["Key_Projects"] = projects[:5]  # Limit to 5 projects
                
                # Trim content if too long
                if len(content) > 8000:
                    content = content[:8000] + "..."
                
                print(f"Sending {len(content)} characters to OpenAI")
                
                try:
                    # Call OpenAI with a very explicit prompt
                    response = client.chat.completions.create(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": """You are an expert at extracting precise organization names. Given a conversation, your ONLY task is to extract the exact organization name mentioned. ONLY return the organization name without any prefixes like "called" or "named". Do not include any descriptions or additional text.

Return a JSON object with the following structure:
{
  "Organization_Overview": "EXACT ORGANIZATION NAME",
  "Key_Projects": ["Project 1", "Project 2"],
  "Team_Members": ["Person 1", "Person 2"]
}"""},
                            {"role": "user", "content": f"Find the exact organization name in this text. If someone says 'I work at Company X' or 'My company is called Company X', just return 'Company X'. DO NOT include words like 'called', 'named', or 'that': {content}"}
                        ],
                        temperature=0,
                        max_tokens=1000
                    )
                    
                    org_info_text = response.choices[0].message.content
                    print(f"AI response received: {org_info_text[:100]}...")
                    
                    try:
                        # Try to parse as JSON
                        org_data = json.loads(org_info_text)
                        print("Successfully parsed JSON response")
                    except json.JSONDecodeError:
                        print("JSON parse error, looking for code block")
                        # Look for JSON in code blocks
                        json_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
                        json_match = re.search(json_pattern, org_info_text)
                        
                        if json_match:
                            try:
                                org_data = json.loads(json_match.group(1))
                                print("Successfully parsed JSON from code block")
                            except json.JSONDecodeError:
                                print("JSON parsing failed, using defaults")
                                org_data = default_info
                        else:
                            print("No JSON found, using regex-extracted data")
                            org_data = default_info
                    
                    # If the AI couldn't find an organization name but we found one with regex, use that
                    if org_name:
                        if (not org_data.get("Organization_Overview") or 
                            "unknown" in org_data.get("Organization_Overview", "").lower() or
                            len(org_data.get("Organization_Overview", "")) < 3):
                            print(f"Using regex-found org name: {org_name}")
                            org_data["Organization_Overview"] = org_name
                        else:
                            # Extra cleanup for the AI-provided org name
                            ai_org_name = org_data["Organization_Overview"]
                            
                            # Handle "called XXX" explicitly
                            if "called " in ai_org_name.lower():
                                ai_org_name = ai_org_name.lower().split("called ")[1].strip()
                                org_data["Organization_Overview"] = ai_org_name.upper() if ai_org_name.isupper() else ai_org_name
                                print(f"Cleaned up AI org name to: {org_data['Organization_Overview']}")
                    
                    # Save to database
                    org_info = OrganizationInfo.query.filter_by(user_id=user_id).first()
                    if not org_info:
                        org_info = OrganizationInfo(user_id=user_id)
                        db.session.add(org_info)
                    
                    org_info.org_info = json.dumps(org_data)
                    org_info.updated_at = datetime.now(timezone.utc)
                    db.session.commit()
                    
                    print(f"✅ Saved new organization info: {org_data}")
                    
                    return jsonify(org_data)
                    
                except Exception as ai_error:
                    print(f"AI processing error: {str(ai_error)}")
                    return jsonify(default_info)
            else:
                # No messages, use defaults
                print(f"No messages for user {username}, using defaults")
                return jsonify(default_info)
        
        # Not a refresh, so return existing data if available
        org_info = OrganizationInfo.query.filter_by(user_id=user_id).first()
        if org_info and org_info.org_info:
            try:
                org_data = json.loads(org_info.org_info)
                print(f"Returning cached org info: {org_data}")
                return jsonify({
                    'success': True,
                    'org_info': org_data,
                    'source': 'cached'
                })
            except json.JSONDecodeError:
                print("Error parsing cached JSON, forcing refresh")
                # Recursive call with refresh=True
                return synthesize_org_info() 
        
        # No valid existing data, run a fresh analysis
        print(f"No valid existing data for user {current_user.username}, running fresh analysis")
        
        # Set refresh parameter in the request
        request.args = dict(request.args)
        request.args['refresh'] = 'true'
        
        # Call again with refresh=True
        return synthesize_org_info()
            
    except Exception as e:
        print(f"❌ Error in synthesize_org_info: {str(e)}")
        username = current_user.username if hasattr(current_user, 'username') else "Unknown"
        return jsonify({
            'success': True,
            'org_info': {
                "Organization_Overview": f"{username}'s Organization",
                "Key_Projects": ["Error occurred", "Please try again"],
                "Team_Members": [username]
            },
            'source': 'error_fallback'
        })

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
def map():
    # Render the map template directly
    return render_template('map.html')

@app.route('/show-map')
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

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('You need to login first.', 'danger')
            return redirect(url_for('login'))
        
        # Check if user has admin attribute and it's True
        if not hasattr(current_user, 'is_admin') or not current_user.is_admin:
            flash('You need admin privileges to access this page.', 'danger')
            return redirect(url_for('landing_page1'))
        
        return f(*args, **kwargs)
    return decorated_function

# Admin routes
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    """Admin dashboard showing system overview"""
    user_count = User.query.count()
    analysis_count = MediaAnalysis.query.count()
    chat_count = Chat.query.count()
    lesson_count = Lesson.query.count()
    
    # Count admin users
    admin_count = 0
    for user in User.query.all():
        if hasattr(user, 'is_admin') and user.is_admin:
            admin_count += 1
    
    # Get Flask version
    import flask
    flask_version = flask.__version__
    
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    
    return render_template(
        'admin/dashboard.html', 
        user_count=user_count,
        analysis_count=analysis_count,
        chat_count=chat_count,
        lesson_count=lesson_count,
        recent_users=recent_users,
        admin_count=admin_count,
        flask_version=flask_version
    )

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    """Admin page to view all users"""
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/user/<int:user_id>')
@login_required
@admin_required
def admin_user_detail(user_id):
    """Admin page to view details of a specific user"""
    user = User.query.get_or_404(user_id)
    
    # Get user's media analyses
    analyses = MediaAnalysis.query.filter_by(user_id=user_id).order_by(MediaAnalysis.created_at.desc()).all()
    
    # Get user's chats
    chats = Chat.query.filter_by(user_id=user_id).order_by(Chat.created_at.desc()).all()
    
    # Get user's lesson progress
    lesson_progress = UserLesson.query.filter_by(user_id=user_id).all()
    
    # Get user's translations
    translations = Translation.query.filter_by(user_id=user_id).order_by(Translation.created_at.desc()).all()
    
    return render_template(
        'admin/user_detail.html',
        user=user,
        analyses=analyses,
        chats=chats,
        lesson_progress=lesson_progress,
        translations=translations
    )

@app.route('/admin/chats')
@login_required
@admin_required
def admin_chats():
    """Admin page to view all chats"""
    chats = Chat.query.order_by(Chat.created_at.desc()).all()
    return render_template('admin/chats.html', chats=chats)

@app.route('/admin/chat/<int:chat_id>')
@login_required
@admin_required
def admin_chat_detail(chat_id):
    """Admin page to view details of a specific chat"""
    chat = Chat.query.get_or_404(chat_id)
    messages = Message.query.filter_by(chat_id=chat_id).order_by(Message.created_at).all()
    return render_template('admin/chat_detail.html', chat=chat, messages=messages)

@app.route('/admin/analyses')
@login_required
@admin_required
def admin_analyses():
    """Admin page to view all media analyses"""
    analyses = MediaAnalysis.query.order_by(MediaAnalysis.created_at.desc()).all()
    return render_template('admin/analyses.html', analyses=analyses)

@app.route('/admin/lessons')
@login_required
@admin_required
def admin_lessons():
    """Admin page to view all lessons"""
    lessons = Lesson.query.order_by(Lesson.order).all()
    return render_template('admin/lessons.html', lessons=lessons)

@app.route('/admin/create_admin', methods=['GET', 'POST'])
@login_required
@admin_required
def create_admin():
    """Admin page to create a new admin user"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Check if user already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists', 'danger')
            return redirect(url_for('create_admin'))
        
        # Create new admin user
        new_admin = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_admin=True
        )
        
        db.session.add(new_admin)
        db.session.commit()
        
        flash(f'Admin user {username} created successfully', 'success')
        return redirect(url_for('admin_users'))
    
    return render_template('admin/create_admin.html')

@app.route('/admin/toggle_admin/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    """Toggle admin status for a user"""
    user = User.query.get_or_404(user_id)
    
    # Prevent removing admin status from yourself
    if user.id == current_user.id:
        flash('You cannot remove your own admin status', 'danger')
        return redirect(url_for('admin_users'))
    
    # Toggle admin status
    user.is_admin = not user.is_admin
    db.session.commit()
    
    status = 'granted' if user.is_admin else 'removed'
    flash(f'Admin status {status} for {user.username}', 'success')
    return redirect(url_for('admin_users'))

@app.route('/content-calendar')
@login_required
def content_calendar():
    """Content Calendar page for AI Utility"""
    # Set the platform in session
    session['platform'] = 'ai_utility'
    return render_template('content_calendar.html', hide_right_sidebar=True)

@app.cli.command("reset-db")
def reset_db():
    """Reset the database tables."""
    db_path = os.path.join(basedir, "instance", "media_analysis.db")
    
    # Create a backup of the old database if it exists
    if os.path.exists(db_path):
        backup_path = db_path + ".backup"
        try:
            import shutil
            shutil.copy2(db_path, backup_path)
            print(f"Created backup at {backup_path}")
        except Exception as e:
            print(f"Warning: Could not create backup: {str(e)}")
        
        # Try to remove the corrupted file
        try:
            os.remove(db_path)
            print(f"Removed existing database file {db_path}")
        except Exception as e:
            print(f"Could not remove existing database: {str(e)}")
            # If we can't remove it, try to create a new database path
            db_path = os.path.join(basedir, "instance", "media_analysis_new.db")
            app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
            print(f"Using new database path: {db_path}")
    
    # Ensure the instance directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # Create all tables in the new database
    with app.app_context():
        try:
            db.create_all()
            print("Database tables created successfully.")
        except Exception as e:
            print(f"Error creating database tables: {str(e)}")

# Create database tables
with app.app_context():
    # First, create all tables that are defined in models
    db.create_all()
    
    # Check if User model has all required columns
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    
    # Use 'users' table name instead of 'user' to match the model definition
    existing_columns = [col['name'] for col in inspector.get_columns('users')]
    
    # Define all expected columns based on your User model
    expected_columns = {
        'is_admin': 'BOOLEAN DEFAULT 0',
        'last_login': 'DATETIME',
        'latitude': 'FLOAT',
        'longitude': 'FLOAT',
        'location_name': 'VARCHAR(200)',
        'has_face_id': 'BOOLEAN DEFAULT 0'
    }
    
    # Add any missing columns
    with db.engine.connect() as conn:
        for column_name, column_type in expected_columns.items():
            if column_name not in existing_columns:
                print(f"Adding {column_name} column to User model")
                # Use text() for raw SQL execution
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"))
                conn.commit()
                print(f"{column_name} column added successfully")
    
    # Check if any admin user exists
    admin_exists = False
    try:
        admin_user = User.query.filter_by(is_admin=True).first()
        if admin_user:
            admin_exists = True
            print(f"Admin user exists: {admin_user.username}")
    except Exception as e:
        print(f"Error checking for admin users: {str(e)}")
    
    # Create default admin if none exists
    if not admin_exists:
        print("Creating default admin user")
        try:
            admin_user = User(
                username="admin",
                email="admin@example.com",
                password_hash=generate_password_hash("admin123"),
                is_admin=True  # Set is_admin directly in constructor
            )
            
            db.session.add(admin_user)
            db.session.commit()
            print("Default admin user created with username 'admin' and password 'admin123'")
        except Exception as e:
            db.session.rollback()
            print(f"Error creating admin user: {str(e)}")

@app.route('/justice-ai')
def justice_ai():
    return render_template('justice_ai.html')

@app.route('/language-ai')
def language_ai():
    return render_template('language_ai.html')

@app.route('/training-lab')
def training_lab():
    return render_template('training_lab.html')

@app.route('/crimecast')
def crimecast():
    return render_template('crimecast.html')

@app.route('/ai-store')
def ai_store():
    """AI Store page"""
    return render_template('ai_store.html')

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

if __name__ == '__main__':
    sys.path.append('/path/to/your/directory')
    app.run(host='0.0.0.0', port=8000, debug=True) 
