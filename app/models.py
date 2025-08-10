from datetime import timedelta
from app import db
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    google_id = Column(String(100), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    avatar_url = Column(String(200))
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship with uploads
    uploads = relationship('Upload', foreign_keys='Upload.user_id', backref='uploader', lazy=True)
    
    def __repr__(self):
        return f'<User {self.email}>'

class Upload(db.Model):
    __tablename__ = 'uploads'
    
    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    md5_hash = Column(String(32), nullable=False)
    
    # Metadata fields
    device_manufacturer = Column(String(100), nullable=False)
    device_model = Column(String(100), nullable=False)
    afh_link = Column(String(500))
    xda_thread = Column(String(500))
    notes = Column(Text)
    
    # Status and timestamps
    status = Column(String(20), default='pending')  # pending, approved, rejected
    rejection_reason = Column(Text)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime)
    download_count = Column(Integer, default=0)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    reviewed_by = Column(Integer, ForeignKey('users.id'))
    
    # Relationships
    reviewer = relationship('User', foreign_keys=[reviewed_by])
    
    def __repr__(self):
        return f'<Upload {self.original_filename}>'
    
    @property
    def file_size_mb(self):
        return round(self.file_size / (1024 * 1024), 2)
    
    @property
    def is_pending(self):
        return self.status == 'pending'
    
    @property
    def is_approved(self):
        return self.status == 'approved'
    
    @property
    def is_rejected(self):
        return self.status == 'rejected'


# Announcement model
class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = Column(Integer, primary_key=True)
    subject = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def is_active(self):
        # Active for 48 hours
        return (datetime.utcnow() - self.created_at) < timedelta(hours=48)


# A/B Testing models
class ABTest(db.Model):
    __tablename__ = 'ab_tests'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    is_active = Column(Boolean, default=False)
    traffic_percentage = Column(Integer, default=50)  # Percentage of users in test group
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    assignments = relationship('ABTestAssignment', backref='test', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<ABTest {self.name}>'


class ABTestAssignment(db.Model):
    __tablename__ = 'ab_test_assignments'
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(128), nullable=False)
    test_id = Column(Integer, ForeignKey('ab_tests.id'), nullable=False)
    variant = Column(String(20), nullable=False)  # 'control' or 'test'
    assigned_at = Column(DateTime, default=datetime.utcnow)
    
    # Index for faster lookups
    __table_args__ = (
        db.Index('idx_session_test', 'session_id', 'test_id'),
    )
    
    def __repr__(self):
        return f'<ABTestAssignment {self.session_id} -> {self.variant}>'
