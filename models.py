from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Add location fields
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    location_name = db.Column(db.String(200))
    
    # Relationships
    analyses = db.relationship('MediaAnalysis', backref='user', lazy=True)
    @property
    def chats(self):
        from models import Chat
        return Chat.query.filter_by(user_id=self.id).all()

class MediaAnalysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    media_url = db.Column(db.String(500), nullable=False)
    analysis_result = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

class Chat(db.Model):
    __tablename__ = 'chats'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    title = db.Column(db.String(255), nullable=True)  # Optional title based on content
    
    # Relationships
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")
    
    def to_dict(self):
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'title': self.title,
            'messages': [message.to_dict() for message in self.messages]
        }

class Message(db.Model):
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # 'user', 'assistant', 'system'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    chat = relationship("Chat", back_populates="messages")
    
    def to_dict(self):
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content,
            'created_at': self.created_at.isoformat()
        }

class Lesson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    order = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserLesson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    last_accessed = db.Column(db.DateTime, default=datetime.utcnow)

class OrganizationInfo(db.Model):
    __tablename__ = 'organization_info'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Make it user-specific
    org_info = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class OrganizationFact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fact = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Translation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    original_text = db.Column(db.Text, nullable=False)
    translated_text = db.Column(db.Text, nullable=False)
    source_language = db.Column(db.String(10))
    target_language = db.Column(db.String(10))
    rating = db.Column(db.Integer)  # Store user rating 1-10
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TranslationFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    translation_id = db.Column(db.Integer, db.ForeignKey('translation.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    corrected_text = db.Column(db.Text, nullable=False)
    source_language = db.Column(db.String(10))
    target_language = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.String(50), nullable=False)
    recipient_id = db.Column(db.String(50), nullable=False)
    message_text = db.Column(db.String(2000), nullable=False)
    timestamp = db.Column(db.DateTime, server_default=func.now())
    is_user_message = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<ChatMessage(message_text='{self.message_text}')>" 