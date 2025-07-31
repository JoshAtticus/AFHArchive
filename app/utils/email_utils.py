import os
import sys
import logging
from decouple import config
from flask import render_template, current_app

# Set up logging
logger = logging.getLogger(__name__)

# Always use AFHArchive as sender name
DEFAULT_FROM = 'AFHArchive <afh@emails.joshattic.us>'
DEFAULT_REPLY_TO = 'afh@joshattic.us'
PROD_BASE_URL = 'https://afh.joshattic.us'


def send_email(to, subject, html, from_addr=None):
    """Send an email using Resend API directly with requests to avoid gevent conflicts"""
    try:
        import requests
        
        # Get API key
        api_key = config('RESEND_API_KEY', default=None)
        if not api_key:
            logger.error('RESEND_API_KEY not set')
            return False
        
        # Prepare email data
        payload = {
            "from": from_addr or DEFAULT_FROM,
            "to": [to] if isinstance(to, str) else to,
            "subject": subject,
            "html": html,
            "reply_to": DEFAULT_REPLY_TO,
        }
        
        # Send via Resend API directly
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"Email sent successfully to {to}")
            return response.json()
        else:
            logger.error(f"Email API error for {to}: {response.status_code} - {response.text}")
            return False
        
    except Exception as e:
        logger.error(f"Email sending failed for {to}: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
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
