"""
SSL Certificate management utilities for AFHArchive
Handles Let's Encrypt certificate management within the Flask application
"""

import os
import subprocess
import logging
from datetime import datetime, timedelta
from flask import current_app
from decouple import config

logger = logging.getLogger(__name__)

class SSLCertificateManager:
    """Flask extension for managing SSL certificates"""
    
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize the extension with Flask app"""
        app.config.setdefault('SSL_DOMAIN', 'direct.afharchive.xyz')
        app.config.setdefault('SSL_EMAIL', config('SSL_EMAIL', default='admin@afharchive.xyz'))
        app.config.setdefault('SSL_CERT_PATH', '/etc/letsencrypt/live')
        app.config.setdefault('SSL_WEBROOT_PATH', '/var/www/certbot')
        app.config.setdefault('SSL_AUTO_RENEW', True)
        app.config.setdefault('SSL_STAGING', config('SSL_STAGING', default=False, cast=bool))
        
        # Store reference to this extension
        app.extensions = getattr(app, 'extensions', {})
        app.extensions['ssl_manager'] = self
        
        # Setup CLI commands
        self._register_cli_commands(app)
        
        # Setup automatic renewal check
        if app.config.get('SSL_AUTO_RENEW'):
            self._setup_auto_renew_check(app)
    
    def _register_cli_commands(self, app):
        """Register Flask CLI commands for SSL management"""
        
        @app.cli.command('ssl-setup')
        def ssl_setup():
            """Setup SSL certificates"""
            success = self.setup_ssl()
            if success:
                app.logger.info("SSL setup completed successfully")
            else:
                app.logger.error("SSL setup failed")
        
        @app.cli.command('ssl-renew')
        def ssl_renew():
            """Renew SSL certificates"""
            success = self.renew_certificate()
            if success:
                app.logger.info("SSL renewal completed")
            else:
                app.logger.error("SSL renewal failed")
        
        @app.cli.command('ssl-check')
        def ssl_check():
            """Check SSL certificate status"""
            expiry = self.check_certificate_expiry()
            if expiry:
                days_left = (expiry - datetime.now()).days
                app.logger.info(f"Certificate expires in {days_left} days ({expiry})")
            else:
                app.logger.warning("No certificate found or unable to check expiry")
    
    def _setup_auto_renew_check(self, app):
        """Setup automatic renewal check on app startup"""
        # Use a more modern approach compatible with Flask 2.3+
        def check_certificate_on_startup():
            """Check certificate status when app starts"""
            with app.app_context():
                if self.needs_renewal():
                    app.logger.warning("SSL certificate needs renewal!")
                    # Optionally trigger renewal automatically
                    # self.renew_certificate()
        
        # Store the check function to be called manually if needed
        app._ssl_startup_check = check_certificate_on_startup
    
    def get_cert_path(self, filename='cert.pem'):
        """Get path to certificate file"""
        domain = current_app.config['SSL_DOMAIN']
        cert_path = current_app.config['SSL_CERT_PATH']
        return os.path.join(cert_path, domain, filename)
    
    def certificate_exists(self):
        """Check if SSL certificate exists"""
        cert_file = self.get_cert_path('cert.pem')
        return os.path.exists(cert_file)
    
    def check_certificate_expiry(self):
        """Check certificate expiration date"""
        if not self.certificate_exists():
            return None
        
        cert_file = self.get_cert_path('cert.pem')
        
        try:
            result = subprocess.run([
                'openssl', 'x509', '-in', cert_file, 
                '-noout', '-enddate'
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                # Parse the date from output like "notAfter=Dec 12 10:30:00 2024 GMT"
                date_str = result.stdout.strip().split('=')[1]
                expiry_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
                return expiry_date
            else:
                logger.error(f"Error checking certificate: {result.stderr}")
                return None
        except Exception as e:
            logger.error(f"Error parsing certificate date: {e}")
            return None
    
    def needs_renewal(self, days_before_expiry=30):
        """Check if certificate needs renewal"""
        if not self.certificate_exists():
            return True  # Need to obtain certificate
        
        expiry_date = self.check_certificate_expiry()
        
        if expiry_date is None:
            return True  # Unable to check, assume renewal needed
        
        days_until_expiry = (expiry_date - datetime.now()).days
        return days_until_expiry <= days_before_expiry
    
    def obtain_certificate(self):
        """Obtain SSL certificate using certbot"""
        domain = current_app.config['SSL_DOMAIN']
        email = current_app.config['SSL_EMAIL']
        webroot_path = current_app.config['SSL_WEBROOT_PATH']
        staging = current_app.config['SSL_STAGING']
        
        # Ensure webroot directory exists
        os.makedirs(webroot_path, exist_ok=True)
        
        cmd = [
            'certbot', 'certonly',
            '--webroot',
            '--webroot-path', webroot_path,
            '--email', email,
            '--agree-tos',
            '--no-eff-email',
            '-d', domain
        ]
        
        if staging:
            cmd.append('--staging')
            logger.info("Using Let's Encrypt staging environment")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"SSL certificate obtained successfully for {domain}")
                return True
            else:
                logger.error(f"Failed to obtain certificate: {result.stderr}")
                return False
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running certbot: {e}")
            return False
    
    def renew_certificate(self):
        """Renew SSL certificate"""
        try:
            result = subprocess.run(['certbot', 'renew'], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("Certificate renewal completed")
                # Reload web server if needed
                self._reload_web_server()
                return True
            else:
                logger.warning(f"Certificate renewal output: {result.stdout}")
                return True  # Certbot returns 0 even if no renewal was needed
        except subprocess.CalledProcessError as e:
            logger.error(f"Error renewing certificate: {e}")
            return False
    
    def _reload_web_server(self):
        """Reload web server configuration"""
        # This could be nginx, apache, or just log a message
        try:
            # Try to reload nginx if it's running
            result = subprocess.run(['systemctl', 'is-active', 'nginx'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
                logger.info("Nginx reloaded successfully")
        except subprocess.CalledProcessError:
            # If nginx is not available, just log
            logger.info("Certificate renewed - web server reload may be required")
    
    def setup_ssl(self):
        """Setup SSL certificate if it doesn't exist"""
        if not self.certificate_exists():
            return self.obtain_certificate()
        else:
            logger.info("SSL certificate already exists")
            return True
    
    def get_certificate_info(self):
        """Get certificate information for admin dashboard"""
        info = {
            'exists': self.certificate_exists(),
            'domain': current_app.config['SSL_DOMAIN'],
            'expiry': None,
            'days_until_expiry': None,
            'needs_renewal': False
        }
        
        if info['exists']:
            expiry = self.check_certificate_expiry()
            if expiry:
                info['expiry'] = expiry
                info['days_until_expiry'] = (expiry - datetime.now()).days
                info['needs_renewal'] = self.needs_renewal()
        
        return info
