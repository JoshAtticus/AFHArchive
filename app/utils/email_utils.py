import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from decouple import config
import resend
from flask import render_template, current_app
import logging

# Set up logging
logger = logging.getLogger(__name__)

# Email Configuration
EMAIL_PROVIDER = config('EMAIL_PROVIDER', default='resend').lower()
DEFAULT_FROM = config('DEFAULT_FROM_EMAIL', default='AFHArchive <mail@afharchive.xyz')
DEFAULT_REPLY_TO = config('DEFAULT_REPLY_TO', default='support@afharchive.xyz')
PROD_BASE_URL = 'https://afharchive.xyz'

# Resend Config
resend.api_key = config('RESEND_API_KEY', default=None)

# SMTP Config
SMTP_SERVER = config('SMTP_SERVER', default='')
SMTP_PORT = config('SMTP_PORT', default=587, cast=int)
SMTP_USERNAME = config('SMTP_USERNAME', default='')
SMTP_PASSWORD = config('SMTP_PASSWORD', default='')
SMTP_USE_TLS = config('SMTP_USE_TLS', default=True, cast=bool)

def send_email(to, subject, html, from_addr=None):
    """Send an email using configured provider (Resend or SMTP)"""
    if EMAIL_PROVIDER == 'smtp':
        return send_smtp_email(to, subject, html, from_addr)
    else:
        return send_resend_email(to, subject, html, from_addr)

def send_smtp_email(to, subject, html, from_addr=None):
    """Send email via SMTP"""
    if not SMTP_SERVER:
        logger.error("SMTP_SERVER not configured")
        return False
        
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = from_addr or DEFAULT_FROM
    msg['To'] = to if isinstance(to, str) else ', '.join(to)
    msg['Reply-To'] = DEFAULT_REPLY_TO

    part = MIMEText(html, 'html')
    msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        if SMTP_USE_TLS:
            server.starttls()
        
        if SMTP_USERNAME and SMTP_PASSWORD:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            
        server.send_message(msg)
        server.quit()
        logger.info(f"SMTP Email sent successfully to {to}")
        return True
    except Exception as e:
        logger.error(f"SMTP email error for {to}: {str(e)}")
        return False

def send_resend_email(to, subject, html, from_addr=None):
    """Send an email using Resend"""
    if not resend.api_key:
        logger.error('RESEND_API_KEY not set')
        return False
    
    params = {
        "from": from_addr or DEFAULT_FROM,
        "to": [to] if isinstance(to, str) else to,
        "subject": subject,
        "html": html,
        "reply_to": DEFAULT_REPLY_TO,
    }
    
    try:
        email = resend.Emails.send(params)
        logger.info(f"Email sent successfully to {to}")
        return email
    except Exception as e:
        logger.error(f"Resend email error for {to}: {str(e)}")
        return False


def render_email_template(template_name, **context):
    """Render an email template from the templates/emails directory, using production URLs."""
    try:
        # Always use production base URL for all links in emails
        context['base_url'] = PROD_BASE_URL
        return render_template(f'emails/{template_name}', **context)
    except Exception as e:
        logger.error(f"Error rendering email template {template_name}: {str(e)}")
        return f"<html><body><p>Error rendering email template: {str(e)}</p></body></html>"
