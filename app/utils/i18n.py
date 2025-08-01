from flask import session, request, redirect, url_for
from flask_babel import _

def set_language(language_code):
    """Set the user's language preference"""
    session['language'] = language_code
    return redirect(request.referrer or url_for('main.index'))

def get_current_language():
    """Get the current language code"""
    return session.get('language', 'en')
