import os
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from decouple import config
import resend
from flask import render_template, current_app

# Set up logging
logger = logging.getLogger(__name__)

# Initialize Resend API key from environment or .env
resend.api_key = config('RESEND_API_KEY', default=None)

# Thread pool for sending emails outside of gevent context
email_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email-sender")


# Always use AFHArchive as sender name
DEFAULT_FROM = 'AFHArchive <afh@emails.joshattic.us>'
DEFAULT_REPLY_TO = 'afh@joshattic.us'
PROD_BASE_URL = 'https://afh.joshattic.us'


def _send_email_sync(to, subject, html, from_addr=None):
    """Internal synchronous email sending function that runs in a separate thread"""
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


def send_email(to, subject, html, from_addr=None):
    """Send an email using Resend via a separate thread to avoid gevent conflicts"""
    try:
        # Submit to thread pool to run outside gevent context
        future = email_executor.submit(_send_email_sync, to, subject, html, from_addr)
        # Wait for completion with a reasonable timeout
        result = future.result(timeout=30)
        return result
    except Exception as e:
        logger.error(f"Email sending failed for {to}: {str(e)}")
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
