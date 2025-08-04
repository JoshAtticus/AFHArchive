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


# Mirror System Models
class Mirror(db.Model):
    __tablename__ = 'mirrors'
    
    id = Column(Integer, primary_key=True)
    server_name = Column(String(100), nullable=False)  # e.g., "Frankfurt Germany", "San Francisco US"
    direct_url = Column(String(500), nullable=False)  # e.g., "123.123.123.123:5000" or "afharchive-sfus.duckdns.org:5000"
    cloudflare_url = Column(String(500))  # e.g., "https://sfus.afharchive.xyz"
    status = Column(String(20), default='pending')  # pending, active, inactive, rejected
    max_files = Column(Integer, default=1000)  # Maximum number of files to store
    current_files = Column(Integer, default=0)  # Current number of files stored
    storage_path = Column(String(500))  # Custom storage path for VM mirrors
    priority = Column(Integer, default=5)  # 1-10, for load balancing
    last_seen = Column(DateTime)
    last_sync = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime)  # When mirror was approved
    approved_by = Column(Integer, ForeignKey('users.id'))  # Who approved it
    api_key = Column(String(64), nullable=False)  # For authentication
    
    # Relationships
    mirror_files = relationship('MirrorFile', backref='mirror', lazy=True, cascade='all, delete-orphan')
    sync_logs = relationship('MirrorSyncLog', backref='mirror', lazy=True, cascade='all, delete-orphan')
    approver = relationship('User', foreign_keys=[approved_by])
    
    def __repr__(self):
        return f'<Mirror {self.server_name}>'
    
    @property
    def is_online(self):
        if not self.last_seen:
            return False
        # Consider online if seen within last 5 minutes
        return (datetime.utcnow() - self.last_seen) < timedelta(minutes=5)
    
    @property 
    def name(self):
        """Legacy property for backwards compatibility"""
        return self.server_name
    
    @property
    def storage_usage_percent(self):
        if self.max_files == 0:
            return 0
        return (self.current_files / self.max_files) * 100


class MirrorFile(db.Model):
    __tablename__ = 'mirror_files'
    
    id = Column(Integer, primary_key=True)
    mirror_id = Column(Integer, ForeignKey('mirrors.id'), nullable=False)
    upload_id = Column(Integer, ForeignKey('uploads.id'), nullable=False)
    file_size = Column(Integer, nullable=False)
    synced_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    upload = relationship('Upload', backref='mirror_copies')
    
    def __repr__(self):
        return f'<MirrorFile mirror_id={self.mirror_id} upload_id={self.upload_id}>'


class MirrorPairingCode(db.Model):
    __tablename__ = 'mirror_pairing_codes'
    
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    used_at = Column(DateTime)
    mirror_id = Column(Integer, ForeignKey('mirrors.id'))
    
    # Relationship
    mirror = relationship('Mirror', backref='pairing_code', uselist=False)
    
    @property
    def is_expired(self):
        return datetime.utcnow() > self.expires_at
    
    @property
    def is_valid(self):
        return not self.used and not self.is_expired
    
    def __repr__(self):
        return f'<MirrorPairingCode {self.code}>'


class MirrorSyncLog(db.Model):
    __tablename__ = 'mirror_sync_logs'
    
    id = Column(Integer, primary_key=True)
    mirror_id = Column(Integer, ForeignKey('mirrors.id'), nullable=False)
    action = Column(String(50), nullable=False)  # 'sync_start', 'sync_complete', 'file_added', 'file_removed', 'error'
    message = Column(Text)
    upload_id = Column(Integer, ForeignKey('uploads.id'))  # Optional, for file-specific actions
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    upload = relationship('Upload')
    
    def __repr__(self):
        return f'<MirrorSyncLog {self.action} for mirror {self.mirror_id}>'
