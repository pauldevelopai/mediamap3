from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
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
import numpy as np
import cv2
from facenet_pytorch import MTCNN, InceptionResnetV1
import torch
from PIL import Image
import io
import traceback
import sys
import insightface
from insightface.app import FaceAnalysis
import torch.nn as nn
import torch.nn.functional as F
import torchvision.transforms as transforms

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
    # Landing page should be accessible without login
    return render_template('landing.html')

@app.route('/select-platform/<platform>')
def select_platform(platform):
    """Store the selected platform and redirect to login"""
    if platform in ['mediamap', 'guardpass', 'contentflow']:
        session['platform'] = platform
        if current_user.is_authenticated:
            return redirect(url_for('logout'))
        return redirect(url_for('login'))
    
    # Add handling for new platforms
    if platform == 'justice':
        return redirect(url_for('justice_ai'))
    elif platform == 'language':
        return redirect(url_for('language_ai'))
    elif platform == 'training':
        return redirect(url_for('training_lab'))
    
    # Fallback for unknown platforms
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login route that checks for platform selection"""
    if current_user.is_authenticated:
        # Redirect to selected platform if already logged in
        platform = session.get('platform')
        if platform == 'mediamap':
            return redirect(url_for('mediamap_home'))
        elif platform == 'guardpass':
            return redirect(url_for('guardpass'))
        elif platform == 'contentflow':
            return redirect(url_for('contentflow'))
        else:
            return redirect(url_for('logout'))
    
    # Check if platform is selected
    if 'platform' not in session:
        flash('Please select a platform first.', 'warning')
        return redirect(url_for('index'))
    
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
                platform = session.get('platform')
                if platform == 'mediamap':
                    return redirect(url_for('mediamap_home'))
                elif platform == 'guardpass':
                    return redirect(url_for('guardpass'))
                elif platform == 'contentflow':
                    return redirect(url_for('contentflow'))
                else:
                    return redirect(url_for('index'))
            else:
                # If no proper password field was found or password didn't match
                flash('Invalid username or password.', 'danger')
        else:
            flash('Invalid username or password.', 'danger')
    
    # Customize login template based on selected platform
    platform = session.get('platform')
    return render_template('login.html', platform=platform)

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
    """MediaMap home page with platform check"""
    if session.get('platform') != 'mediamap':
        flash('Access denied. Please select the correct platform.', 'danger')
        return redirect(url_for('logout'))
    return render_template('index.html')

@app.route('/guardpass')
@login_required
def guardpass():
    """GuardPass home page with platform check"""
    if session.get('platform') != 'guardpass':
        flash('Access denied. Please select the correct platform.', 'danger')
        return redirect(url_for('logout'))
    return render_template('guardpass.html', hide_right_sidebar=True)

@app.route('/contentflow')
@login_required
def contentflow():
    """ContentFlow home page with platform check"""
    if session.get('platform') != 'contentflow':
        flash('Access denied. Please select the correct platform.', 'danger')
        return redirect(url_for('logout'))
    return render_template('contentflow.html', hide_right_sidebar=True)

@app.route('/access-controls')
@login_required
def access_controls():
    """Access Controls page for GuardPass"""
    if session.get('platform') != 'guardpass':
        flash('Access denied. Please select the correct platform.', 'danger')
        return redirect(url_for('logout'))
    return render_template('access_controls.html', hide_right_sidebar=True)

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

@app.route('/content-calendar')
@login_required
def content_calendar():
    """Content Calendar page for ContentFlow"""
    if session.get('platform') != 'contentflow':
        flash('Access denied. Please select the correct platform.', 'danger')
        return redirect(url_for('logout'))
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
    db.create_all()

# Create directory for storing face embeddings if it doesn't exist
os.makedirs('face_db', exist_ok=True)

# Initialize InsightFace model
print("Initializing InsightFace model...")
face_app = FaceAnalysis(providers=['CPUExecutionProvider'])
face_app.prepare(ctx_id=0, det_size=(640, 640))
print("InsightFace model loaded successfully")

def get_face_embedding(img_data):
    """Convert an image to a face embedding vector using InsightFace"""
    try:
        print("Starting face embedding extraction with InsightFace...")
        
        # Convert bytes to numpy array/image
        if isinstance(img_data, bytes):
            print(f"Converting {len(img_data)} bytes to image")
            nparr = np.frombuffer(img_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            # Convert BGR to RGB (InsightFace expects RGB)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        else:
            print(f"Using provided numpy array")
            img = img_data
            
        print(f"Image shape: {img.shape}")
        
        # Detect and analyze faces
        print("Detecting faces with InsightFace...")
        faces = face_app.get(img)
        
        if len(faces) == 0:
            print("No faces detected in the image")
            return None, "No face detected"
        
        print(f"Detected {len(faces)} faces")
        
        if len(faces) > 1:
            print("Multiple faces detected, using the largest one")
            # Find the face with the largest bounding box area
            areas = [(face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1]) for face in faces]
            largest_face_idx = np.argmax(areas)
            face = faces[largest_face_idx]
        else:
            face = faces[0]
        
        # Get embedding directly from the face object
        print("Getting embedding vector...")
        embedding = face.embedding
        print(f"Embedding shape: {embedding.shape}")
        
        return embedding, None
    
    except Exception as e:
        print(f"Exception in get_face_embedding: {str(e)}")
        print(traceback.format_exc())
        return None, str(e)

def identify_face(img_data, threshold=0.5):  # Lower threshold for ArcFace
    print("--- Starting face identification with ArcFace ---")
    # Get embedding for the current face
    print("Attempting to get face embedding...")
    current_embedding, error = get_face_embedding(img_data)
    
    if error:
        print(f"ERROR in get_face_embedding: {error}")
        return None, error
    
    print(f"Successfully got embedding, shape: {current_embedding.shape if current_embedding is not None else 'None'}")
    
    # Load all stored embeddings
    max_similarity = 0
    best_match = None
    
    # Check if face_db directory exists
    face_db_path = os.path.join(os.getcwd(), 'face_db')
    print(f"Looking for faces in: {face_db_path}")
    
    if not os.path.exists(face_db_path):
        print("face_db directory doesn't exist!")
        os.makedirs(face_db_path, exist_ok=True)
        return None, "No faces registered (directory missing)"
    
    # Load mapping of user_ids to names
    name_mapping = {}
    registry_path = os.path.join(face_db_path, 'face_registry.txt')
    print(f"Checking registry at: {registry_path}")
    
    try:
        if os.path.exists(registry_path):
            with open(registry_path, 'r') as f:
                for line in f:
                    parts = line.strip().split('|')
                    if len(parts) >= 2:
                        name_mapping[parts[0]] = parts[1]
            print(f"Loaded name mappings: {name_mapping}")
        else:
            print("Registry file doesn't exist")
    except Exception as e:
        print(f"Error reading registry: {str(e)}")
        print(traceback.format_exc())
    
    # List all files in face_db
    npy_files = [f for f in os.listdir(face_db_path) if f.endswith('.npy')]
    print(f"Found {len(npy_files)} .npy files: {npy_files}")
    
    if not npy_files:
        return None, "No faces registered (no .npy files)"
    
    # Check each registered face
    for filename in npy_files:
        user_id = filename.split('.')[0]
        try:
            embedding_path = os.path.join(face_db_path, filename)
            print(f"Loading embedding from: {embedding_path}")
            embedding = np.load(embedding_path)
            print(f"Loaded embedding shape: {embedding.shape}")
            
            # Calculate similarity - cosine similarity
            similarity = np.dot(current_embedding, embedding) / (
                np.linalg.norm(current_embedding) * np.linalg.norm(embedding)
            )
            
            print(f"Similarity with {user_id}: {similarity}")
            
            # Keep track of best match
            if similarity > max_similarity:
                max_similarity = similarity
                best_match = user_id
                print(f"New best match: {user_id} with similarity {similarity}")
        except Exception as e:
            print(f"Error processing {filename}: {str(e)}")
            print(traceback.format_exc())
            continue
    
    # Return best match if above threshold
    if max_similarity >= threshold:
        name = name_mapping.get(best_match, f"Unknown-{best_match}")
        print(f"Match found: {name} with confidence {max_similarity}")
        return {
            "user_id": best_match,
            "name": name,
            "confidence": float(max_similarity)
        }, None
    else:
        print(f"No match found above threshold. Best: {max_similarity:.2f}")
        return None, f"No match found (best similarity: {max_similarity:.2f})"

# Route for face recognition
@app.route('/guardpass/setup-face-recognition', methods=['GET', 'POST'])
@login_required
def setup_face_recognition():
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'face_image' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
        
        file = request.files['face_image']
        name = request.form.get('name', current_user.username)
        
        # If user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        
        # Process the image
        try:
            img_data = file.read()
            success, error = register_face(name, current_user.id, img_data)
            
            if success:
                flash('Face registered successfully!', 'success')
                # Update user profile
                current_user.has_face_id = True
                db.session.commit()
            else:
                flash(f'Error registering face: {error}', 'danger')
        
        except Exception as e:
            flash(f'Error processing image: {str(e)}', 'danger')
        
        return redirect(url_for('guardpass'))
    
    return render_template('setup_face_recognition.html')

# Route for scanning and identifying faces
@app.route('/guardpass/scan-face', methods=['GET', 'POST'])
@login_required
def scan_face():
    error_message = None
    debug_info = None
    
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'face_image' not in request.files:
            flash('No image was provided', 'danger')
            return redirect(request.url)
        
        file = request.files['face_image']
        
        # If user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        
        # Process the image
        try:
            # Print debug info
            print(f"Processing image: {file.filename}, size: {file.content_length} bytes")
            
            # Read the file
            img_data = file.read()
            print(f"Image data size: {len(img_data)} bytes")
            
            # Store debug information
            debug_info = {
                "filename": file.filename,
                "file_size": len(img_data),
                "content_type": file.content_type
            }
            
            # Check if any faces are registered
            face_dir = os.path.join(os.getcwd(), 'face_db')
            if not os.path.exists(face_dir):
                os.makedirs(face_dir, exist_ok=True)
            
            npy_files = [f for f in os.listdir(face_dir) if f.endswith('.npy')]
            if not npy_files:
                error_message = 'No faces registered in the database. Please register at least one face first.'
                flash(error_message, 'warning')
                return render_template('scan_face.html', result=None, error_message=error_message, debug_info=debug_info)
            
            # Try to identify the face
            try:
                # This is where problems might be occurring
                person, error = identify_face(img_data)
                
                if person:
                    # Log the identification
                    log_path = os.path.join(face_dir, 'identification_log.txt')
                    with open(log_path, 'a') as f:
                        f.write(f"{datetime.now().isoformat()}|{person['user_id']}|{person['name']}|{person['confidence']}\n")
                    
                    flash(f"Identified: {person['name']} (Confidence: {person['confidence']:.2f})", 'success')
                    return render_template('scan_face.html', result=person, debug_info=debug_info)
                else:
                    error_message = f'No match found: {error}'
                    flash(error_message, 'warning')
            except Exception as e:
                import traceback
                error_traceback = traceback.format_exc()
                error_message = f"Error in identify_face: {str(e)}\n{error_traceback}"
                print(error_message)
                flash(f'Error identifying face: {str(e)}', 'danger')
        
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            error_message = f"Error processing image: {str(e)}\n{error_traceback}"
            print(error_message)
            flash(f'Error processing image: {str(e)}', 'danger')
        
        # Return template with error instead of redirecting
        return render_template('scan_face.html', result=None, error_message=error_message, debug_info=debug_info)
    
    return render_template('scan_face.html', result=None)

@app.route('/justice-ai')
def justice_ai():
    return render_template('justice_ai.html')

@app.route('/language-ai')
def language_ai():
    return render_template('language_ai.html')

@app.route('/training-lab')
def training_lab():
    return render_template('training_lab.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True) 
