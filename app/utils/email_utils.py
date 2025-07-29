import os
from decouple import config
import resend
from flask import render_template, current_app

# Initialize Resend API key from environment or .env
resend.api_key = config('RESEND_API_KEY', default=None)


# Always use AFHArchive as sender name
DEFAULT_FROM = 'AFHArchive <afh@emails.joshattic.us>'
DEFAULT_REPLY_TO = 'afh@joshattic.us'
PROD_BASE_URL = 'https://afh.joshattic.us'


def send_email(to, subject, html, from_addr=None):
    """Send an email using Resend"""
    if not resend.api_key:
        current_app.logger.error('RESEND_API_KEY not set')
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
        return email
    except Exception as e:
        current_app.logger.error(f"Resend email error: {e}")
        return False


def render_email_template(template_name, **context):
    """Render an email template from the templates/emails directory, using production URLs."""
    # Always use production base URL for all links in emails
    context['base_url'] = PROD_BASE_URL
    return render_template(f'emails/{template_name}', **context)
