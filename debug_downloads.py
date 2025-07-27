#!/usr/bin/env python3
"""
Production Debugging Guide for AFH Archive API Downloads

This script demonstrates how to debug 404 download issues using the new diagnostic endpoints.
"""

import requests
import json
import sys

def check_api_health(base_url):
    """Check API health status"""
    try:
        response = requests.get(f"{base_url}/api/health")
        if response.status_code == 200:
            data = response.json()
            print("✅ API Health Check - HEALTHY")
            print(f"   Total uploads: {data['database']['total_uploads']}")
            print(f"   Approved uploads: {data['database']['approved_uploads']}")
            print(f"   Upload directory exists: {data['storage']['exists']}")
            print(f"   Upload directory writable: {data['storage']['writable']}")
            return True
        else:
            print(f"❌ API Health Check - UNHEALTHY (Status: {response.status_code})")
            return False
    except Exception as e:
        print(f"❌ API Health Check - ERROR: {str(e)}")
        return False

def debug_upload(base_url, upload_id):
    """Debug specific upload ID"""
    try:
        response = requests.get(f"{base_url}/api/debug/upload/{upload_id}")
        if response.status_code == 200:
            data = response.json()
            print(f"\n📋 Debug Info for Upload ID {upload_id}:")
            print(f"   ✅ Upload exists: {data['exists']}")
            print(f"   📊 Status: {data['status']}")
            print(f"   ✅ Approved: {data['is_approved']}")
            print(f"   📁 Original filename: {data['original_filename']}")
            print(f"   💾 File path (stored): {data['file_path_stored']}")
            print(f"   🔗 File path (resolved): {data['file_path_resolved']}")
            print(f"   📂 File exists: {data['file_exists']}")
            print(f"   📖 File readable: {data['file_readable']}")
            print(f"   📏 Size in DB: {data['file_size_in_db']} bytes")
            print(f"   📏 Size on disk: {data['file_size_on_disk']} bytes")
            print(f"   ✅ Size matches: {data['size_matches']}")
            
            # Determine if download should work
            should_work = (data['exists'] and data['is_approved'] and 
                          data['file_exists'] and data['file_readable'])
            print(f"   🎯 Download should work: {'✅ YES' if should_work else '❌ NO'}")
            
            if not should_work:
                print(f"\n🔍 Issues identified:")
                if not data['exists']:
                    print("   - Upload record not found in database")
                elif not data['is_approved']:
                    print(f"   - Upload status is '{data['status']}' (needs to be 'approved')")
                elif not data['file_exists']:
                    print("   - File does not exist on disk")
                elif not data['file_readable']:
                    print("   - File exists but is not readable (permission issue)")
                    
        elif response.status_code == 404:
            data = response.json()
            print(f"\n❌ Upload ID {upload_id} not found")
            print(f"   Error: {data.get('error', 'Unknown error')}")
        else:
            print(f"\n❌ Debug request failed (Status: {response.status_code})")
    except Exception as e:
        print(f"\n❌ Debug request error: {str(e)}")

def test_download(base_url, upload_id):
    """Test actual download"""
    try:
        print(f"\n🔽 Testing download for Upload ID {upload_id}...")
        response = requests.get(f"{base_url}/api/download/{upload_id}")
        if response.status_code == 200:
            print("   ✅ Download successful!")
            print(f"   📁 Filename: {response.headers.get('Content-Disposition', 'N/A')}")
            print(f"   📏 Content-Length: {response.headers.get('Content-Length', 'N/A')} bytes")
        elif response.status_code == 404:
            print("   ❌ Download failed - 404 Not Found")
        else:
            print(f"   ❌ Download failed - Status: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Download error: {str(e)}")

def main():
    if len(sys.argv) != 3:
        print("Usage: python debug_downloads.py <base_url> <upload_id>")
        print("Example: python debug_downloads.py https://afh.joshattic.us 1")
        sys.exit(1)
    
    base_url = sys.argv[1].rstrip('/')
    upload_id = sys.argv[2]
    
    print(f"🔍 AFH Archive Download Debug Tool")
    print(f"   Base URL: {base_url}")
    print(f"   Upload ID: {upload_id}")
    print("=" * 50)
    
    # 1. Check API health
    if not check_api_health(base_url):
        print("\n⚠️  API appears to be unhealthy. Check server logs.")
        return
    
    # 2. Debug the specific upload
    debug_upload(base_url, upload_id)
    
    # 3. Test the actual download
    test_download(base_url, upload_id)
    
    print("\n" + "=" * 50)
    print("🎯 Debugging complete!")
    print("\nIf issues persist:")
    print("1. Check server logs for detailed error messages")
    print("2. Verify database connectivity and upload records")
    print("3. Check file system permissions in upload directory")
    print("4. Ensure web server is properly routing /api/* requests")

if __name__ == '__main__':
    main()