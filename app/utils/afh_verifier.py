"""
Utility for verifying MD5 hashes against AndroidFileHost
"""
import requests
from bs4 import BeautifulSoup
import re
from flask import current_app


def fetch_afh_md5(afh_url):
    """
    Fetch MD5 hash from an AndroidFileHost URL
    
    Args:
        afh_url: URL to the AndroidFileHost file page
        
    Returns:
        tuple: (md5_hash, error_message)
            - md5_hash: The MD5 hash string if found, None otherwise
            - error_message: Error description if any, None otherwise
    """
    if not afh_url or not afh_url.strip():
        return None, "No AFH link provided"
    
    try:
        # Set a reasonable timeout and user agent
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        current_app.logger.info(f"Fetching AFH page: {afh_url}")
        response = requests.get(afh_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for the MD5 hash in the specific structure
        # <span class="file-attr-value">b455463b5d8f2a7007efa5269536f310<br><span class="file-attr-label">MD5</span></span>
        
        # Method 1: Find by class and structure
        file_attr_values = soup.find_all('span', class_='file-attr-value')
        for span in file_attr_values:
            # Check if it contains a nested span with "MD5" label
            label_span = span.find('span', class_='file-attr-label')
            if label_span and 'MD5' in label_span.get_text():
                # Extract the MD5 hash (it's the text before the <br> tag)
                md5_text = span.get_text(separator='|').split('|')[0].strip()
                # Validate MD5 format (32 hexadecimal characters)
                if re.match(r'^[a-fA-F0-9]{32}$', md5_text):
                    current_app.logger.info(f"Found MD5 hash: {md5_text}")
                    return md5_text.lower(), None
        
        # Method 2: Try to find MD5 hash using regex pattern
        md5_pattern = re.compile(r'([a-fA-F0-9]{32})')
        matches = md5_pattern.findall(response.text)
        if matches:
            # Look for context that indicates it's an MD5 hash
            for match in matches:
                # Check if "MD5" appears near this hash in the HTML
                if f'{match}' in response.text and 'MD5' in response.text[
                    max(0, response.text.index(match) - 200):
                    min(len(response.text), response.text.index(match) + 200)
                ]:
                    current_app.logger.info(f"Found MD5 hash via regex: {match}")
                    return match.lower(), None
        
        current_app.logger.warning(f"Could not find MD5 hash on AFH page: {afh_url}")
        return None, "MD5 hash not found on AFH page"
        
    except requests.exceptions.Timeout:
        current_app.logger.error(f"Timeout fetching AFH page: {afh_url}")
        return None, "Request timeout"
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Error fetching AFH page: {e}")
        return None, f"Network error: {str(e)}"
    except Exception as e:
        current_app.logger.error(f"Unexpected error fetching AFH MD5: {e}")
        return None, f"Error: {str(e)}"


def verify_md5_against_afh(upload):
    """
    Verify an upload's MD5 hash against AndroidFileHost
    
    Args:
        upload: Upload model instance
        
    Returns:
        str: Verification status - 'match', 'mismatch', or 'error'
    """
    if not upload.afh_link:
        return 'no_link'
    
    afh_md5, error = fetch_afh_md5(upload.afh_link)
    
    if error:
        current_app.logger.warning(f"AFH verification failed for upload {upload.id}: {error}")
        return 'error'
    
    if not afh_md5:
        return 'error'
    
    # Compare MD5 hashes (case-insensitive)
    upload_md5 = upload.md5_hash.lower() if upload.md5_hash else ''
    
    if afh_md5 == upload_md5:
        current_app.logger.info(f"MD5 match for upload {upload.id}")
        return 'match'
    else:
        current_app.logger.warning(f"MD5 mismatch for upload {upload.id}: {upload_md5} != {afh_md5}")
        return 'mismatch'
