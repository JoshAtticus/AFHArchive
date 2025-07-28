from flask import Blueprint, render_template, request
from werkzeug.exceptions import HTTPException

errors_bp = Blueprint('errors', __name__)

class UnstableConnectionError(HTTPException):
    """Custom exception for HTTP 215 - Unstable Connection"""
    code = 215
    description = 'The connection to the server is unstable.'

@errors_bp.app_errorhandler(400)
def bad_request_error(error):
    """Handle 400 Bad Request errors"""
    return render_template('errors/400.html', error=error), 400

@errors_bp.app_errorhandler(403)
def forbidden_error(error):
    """Handle 403 Forbidden errors"""
    return render_template('errors/403.html', error=error), 403

@errors_bp.app_errorhandler(404)
def not_found_error(error):
    """Handle 404 Not Found errors"""
    return render_template('errors/404.html', error=error), 404

@errors_bp.app_errorhandler(413)
def payload_too_large_error(error):
    """Handle 413 Payload Too Large errors (file upload size exceeded)"""
    return render_template('errors/413.html', error=error), 413

@errors_bp.app_errorhandler(UnstableConnectionError)
def unstable_connection_error(error):
    """Handle 215 Unstable Connection errors (non-standard)"""
    return render_template('errors/215.html', error=error), 215

@errors_bp.app_errorhandler(429)
def too_many_requests_error(error):
    """Handle 429 Too Many Requests errors (rate limiting)"""
    return render_template('errors/429.html', error=error), 429

@errors_bp.app_errorhandler(500)
def internal_server_error(error):
    """Handle 500 Internal Server Error"""
    return render_template('errors/500.html', error=error), 500

@errors_bp.app_errorhandler(502)
def bad_gateway_error(error):
    """Handle 502 Bad Gateway errors"""
    return render_template('errors/502.html', error=error), 502

@errors_bp.app_errorhandler(503)
def service_unavailable_error(error):
    """Handle 503 Service Unavailable errors"""
    return render_template('errors/503.html', error=error), 503

@errors_bp.app_errorhandler(HTTPException)
def handle_http_exception(error):
    """Generic handler for any HTTP exception not specifically handled"""
    template_name = f'errors/{error.code}.html'
    try:
        return render_template(template_name, error=error), error.code
    except:
        # Fall back to generic error template
        return render_template('errors/generic.html', error=error), error.code
