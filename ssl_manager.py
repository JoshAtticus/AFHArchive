#!/usr/bin/env python3
"""
SSL Certificate Manager for AFHArchive using Let's Encrypt
Manages SSL certificates for direct.afharchive.xyz
"""

import os
import sys
import subprocess
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from decouple import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ssl_manager.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SSLManager:
    """Manages Let's Encrypt SSL certificates"""
    
    def __init__(self):
        self.domain = config('SSL_DOMAIN', default='direct.afharchive.xyz')
        self.email = config('SSL_EMAIL', default='admin@afharchive.xyz')
        self.cert_path = config('SSL_CERT_PATH', default='/etc/letsencrypt/live')
        self.webroot_path = config('SSL_WEBROOT_PATH', default='/var/www/certbot')
        self.nginx_conf_path = config('NGINX_CONF_PATH', default='/etc/nginx/sites-available/afharchive')
        self.staging = config('SSL_STAGING', default=False, cast=bool)
        
        # Ensure webroot directory exists
        os.makedirs(self.webroot_path, exist_ok=True)
    
    def is_certbot_installed(self):
        """Check if certbot is installed"""
        try:
            result = subprocess.run(['certbot', '--version'], capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    def install_certbot(self):
        """Install certbot using system package manager"""
        logger.info("Installing certbot...")
        try:
            # Try different package managers
            if subprocess.run(['which', 'apt-get'], capture_output=True).returncode == 0:
                subprocess.run(['sudo', 'apt-get', 'update'], check=True)
                subprocess.run(['sudo', 'apt-get', 'install', '-y', 'certbot'], check=True)
            elif subprocess.run(['which', 'yum'], capture_output=True).returncode == 0:
                subprocess.run(['sudo', 'yum', 'install', '-y', 'certbot'], check=True)
            elif subprocess.run(['which', 'dnf'], capture_output=True).returncode == 0:
                subprocess.run(['sudo', 'dnf', 'install', '-y', 'certbot'], check=True)
            else:
                # Fallback to snap
                subprocess.run(['sudo', 'snap', 'install', 'core'], check=True)
                subprocess.run(['sudo', 'snap', 'refresh', 'core'], check=True)
                subprocess.run(['sudo', 'snap', 'install', '--classic', 'certbot'], check=True)
                subprocess.run(['sudo', 'ln', '-s', '/snap/bin/certbot', '/usr/bin/certbot'], check=True)
            
            logger.info("Certbot installed successfully")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install certbot: {e}")
            return False
    
    def obtain_certificate(self):
        """Obtain SSL certificate using webroot method"""
        if not self.is_certbot_installed():
            if not self.install_certbot():
                return False
        
        logger.info(f"Obtaining SSL certificate for {self.domain}")
        
        cmd = [
            'sudo', 'certbot', 'certonly',
            '--webroot',
            '--webroot-path', self.webroot_path,
            '--email', self.email,
            '--agree-tos',
            '--no-eff-email',
            '-d', self.domain
        ]
        
        if self.staging:
            cmd.append('--staging')
            logger.info("Using Let's Encrypt staging environment")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"SSL certificate obtained successfully for {self.domain}")
                return True
            else:
                logger.error(f"Failed to obtain certificate: {result.stderr}")
                return False
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running certbot: {e}")
            return False
    
    def renew_certificate(self):
        """Renew SSL certificate"""
        logger.info("Attempting to renew SSL certificate")
        
        try:
            result = subprocess.run(['sudo', 'certbot', 'renew'], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("Certificate renewal completed")
                return True
            else:
                logger.warning(f"Certificate renewal output: {result.stdout}")
                return True  # Certbot returns 0 even if no renewal was needed
        except subprocess.CalledProcessError as e:
            logger.error(f"Error renewing certificate: {e}")
            return False
    
    def check_certificate_expiry(self):
        """Check certificate expiration date"""
        cert_file = Path(self.cert_path) / self.domain / 'cert.pem'
        
        if not cert_file.exists():
            logger.warning(f"Certificate file not found: {cert_file}")
            return None
        
        try:
            result = subprocess.run([
                'openssl', 'x509', '-in', str(cert_file), 
                '-noout', '-enddate'
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                # Parse the date from output like "notAfter=Dec 12 10:30:00 2024 GMT"
                date_str = result.stdout.strip().split('=')[1]
                expiry_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
                logger.info(f"Certificate expires on: {expiry_date}")
                return expiry_date
            else:
                logger.error(f"Error checking certificate: {result.stderr}")
                return None
        except Exception as e:
            logger.error(f"Error parsing certificate date: {e}")
            return None
    
    def needs_renewal(self, days_before_expiry=30):
        """Check if certificate needs renewal"""
        expiry_date = self.check_certificate_expiry()
        
        if expiry_date is None:
            return True  # Need to obtain certificate
        
        days_until_expiry = (expiry_date - datetime.now()).days
        logger.info(f"Certificate expires in {days_until_expiry} days")
        
        return days_until_expiry <= days_before_expiry
    
    def create_nginx_config(self):
        """Create nginx configuration with SSL support"""
        nginx_config = f"""# AFHArchive SSL Configuration for {self.domain}

upstream afharchive_app {{
    server 127.0.0.1:8000;
}}

# Redirect HTTP to HTTPS
server {{
    listen 80;
    server_name {self.domain};
    
    # Let's Encrypt verification
    location /.well-known/acme-challenge/ {{
        root {self.webroot_path};
    }}
    
    # Redirect all other traffic to HTTPS
    location / {{
        return 301 https://$server_name$request_uri;
    }}
}}

# HTTPS server
server {{
    listen 443 ssl http2;
    server_name {self.domain};
    
    # SSL Configuration
    ssl_certificate {self.cert_path}/{self.domain}/fullchain.pem;
    ssl_certificate_key {self.cert_path}/{self.domain}/privkey.pem;
    
    # SSL Security Settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-SHA256:ECDHE-RSA-AES256-SHA384:ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:DHE-RSA-AES128-SHA256:DHE-RSA-AES256-SHA256:DHE-RSA-AES128-SHA:DHE-RSA-AES256-SHA:ECDHE-RSA-DES-CBC3-SHA:EDH-RSA-DES-CBC3-SHA:AES128-GCM-SHA256:AES256-GCM-SHA384:AES128-SHA256:AES256-SHA256:AES128-SHA:AES256-SHA:DES-CBC3-SHA:HIGH:!aNULL:!eNULL:!EXPORT:!DES:!MD5:!PSK:!RC4;
    ssl_prefer_server_ciphers on;
    ssl_dhparam /etc/nginx/dhparam.pem;
    
    # HSTS (optional but recommended)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload";
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    
    # Client upload limit (5GB to match Flask config)
    client_max_body_size 5G;
    
    # Timeout settings for large file uploads
    proxy_connect_timeout 300s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;
    
    # Let's Encrypt verification
    location /.well-known/acme-challenge/ {{
        root {self.webroot_path};
    }}
    
    # Main application
    location / {{
        proxy_pass http://afharchive_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # For large file downloads
        proxy_buffering off;
        proxy_request_buffering off;
    }}
    
    # Static files optimization
    location /static/ {{
        alias /path/to/your/static/files/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }}
}}
"""
        
        try:
            with open(self.nginx_conf_path, 'w') as f:
                f.write(nginx_config)
            logger.info(f"Nginx configuration created: {self.nginx_conf_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create nginx config: {e}")
            return False
    
    def reload_nginx(self):
        """Reload nginx configuration"""
        try:
            # Test nginx configuration first
            result = subprocess.run(['sudo', 'nginx', '-t'], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Nginx configuration test failed: {result.stderr}")
                return False
            
            # Reload nginx
            subprocess.run(['sudo', 'systemctl', 'reload', 'nginx'], check=True)
            logger.info("Nginx reloaded successfully")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to reload nginx: {e}")
            return False
    
    def setup_ssl(self):
        """Complete SSL setup process"""
        logger.info("Starting SSL setup process...")
        
        # Step 1: Create nginx config with HTTP only for initial verification
        if not self.create_nginx_config():
            return False
        
        # Step 2: Generate DH parameters if they don't exist
        dhparam_file = '/etc/nginx/dhparam.pem'
        if not os.path.exists(dhparam_file):
            logger.info("Generating DH parameters (this may take a while)...")
            try:
                subprocess.run(['sudo', 'openssl', 'dhparam', '-out', dhparam_file, '2048'], check=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to generate DH parameters: {e}")
                return False
        
        # Step 3: Obtain certificate
        if not self.obtain_certificate():
            return False
        
        # Step 4: Update nginx config with SSL
        if not self.create_nginx_config():
            return False
        
        # Step 5: Enable nginx site
        sites_enabled = '/etc/nginx/sites-enabled/afharchive'
        if not os.path.exists(sites_enabled):
            try:
                subprocess.run(['sudo', 'ln', '-s', self.nginx_conf_path, sites_enabled], check=True)
                logger.info("Nginx site enabled")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to enable nginx site: {e}")
                return False
        
        # Step 6: Reload nginx
        if not self.reload_nginx():
            return False
        
        logger.info("SSL setup completed successfully!")
        return True
    
    def setup_auto_renewal(self):
        """Setup automatic certificate renewal via cron"""
        cron_command = f"0 12 * * * /usr/bin/certbot renew --quiet && /usr/bin/systemctl reload nginx"
        
        try:
            # Add to root's crontab
            subprocess.run(['sudo', 'crontab', '-l'], capture_output=True, check=False)
            result = subprocess.run(['sudo', 'crontab', '-l'], capture_output=True, text=True)
            current_cron = result.stdout if result.returncode == 0 else ""
            
            if cron_command not in current_cron:
                new_cron = current_cron + f"\n{cron_command}\n"
                process = subprocess.Popen(['sudo', 'crontab', '-'], stdin=subprocess.PIPE, text=True)
                process.communicate(input=new_cron)
                
                if process.returncode == 0:
                    logger.info("Auto-renewal cron job added")
                    return True
                else:
                    logger.error("Failed to add cron job")
                    return False
            else:
                logger.info("Auto-renewal cron job already exists")
                return True
        except Exception as e:
            logger.error(f"Error setting up auto-renewal: {e}")
            return False

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python ssl_manager.py [setup|renew|check|create-config]")
        sys.exit(1)
    
    command = sys.argv[1]
    ssl_manager = SSLManager()
    
    if command == 'setup':
        success = ssl_manager.setup_ssl()
        if success:
            ssl_manager.setup_auto_renewal()
        sys.exit(0 if success else 1)
    
    elif command == 'renew':
        success = ssl_manager.renew_certificate()
        if success:
            ssl_manager.reload_nginx()
        sys.exit(0 if success else 1)
    
    elif command == 'check':
        if ssl_manager.needs_renewal():
            print("Certificate needs renewal")
            sys.exit(1)
        else:
            print("Certificate is valid")
            sys.exit(0)
    
    elif command == 'create-config':
        success = ssl_manager.create_nginx_config()
        sys.exit(0 if success else 1)
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == '__main__':
    main()
