# API Download 404 Issue Resolution

## Overview
This document explains the resolution for API download 404 errors in the AFH Archive application.

## Problem Description
Downloads from the API endpoints like `https://afh.joshattic.us/api/download/1` were returning 404 errors. The root cause could be one of several issues:

1. Upload record not found in database
2. Upload exists but status is not 'approved'
3. Upload approved but file missing from disk
4. File exists but not readable due to permissions
5. Web server configuration not routing API requests properly

## Solution Implemented

### 1. Enhanced Error Handling and Logging
The download endpoint now includes comprehensive logging and error handling:

```python
@api_bp.route('/download/<int:upload_id>')
def download_file(upload_id):
    try:
        # Log the download request
        current_app.logger.info(f'Download request for upload ID: {upload_id}')
        
        # Validate upload exists
        upload = Upload.query.get(upload_id)
        if not upload:
            current_app.logger.warning(f'Upload not found: {upload_id}')
            abort(404)
        
        # Validate upload is approved
        if upload.status != 'approved':
            current_app.logger.warning(f'Upload not approved: {upload_id}, status: {upload.status}')
            abort(404)
        
        # Validate file exists and is readable
        # ... (detailed file validation)
        
    except Exception as e:
        current_app.logger.error(f'Unexpected error in download_file: {str(e)}')
        abort(404)
```

### 2. Diagnostic Endpoints

#### Health Check Endpoint
`GET /api/health`

Returns API status, database connectivity, and configuration information:

```json
{
  "status": "healthy",
  "timestamp": "2025-07-27T12:22:46.507696Z",
  "database": {
    "connected": true,
    "total_uploads": 4,
    "approved_uploads": 3
  },
  "storage": {
    "upload_dir": "uploads",
    "exists": true,
    "writable": true
  },
  "config": {
    "max_content_length": 5368709120,
    "download_speed_limit": 10485760
  }
}
```

#### Upload Debug Endpoint
`GET /api/debug/upload/<upload_id>`

Returns detailed information about a specific upload:

```json
{
  "upload_id": 1,
  "exists": true,
  "status": "approved",
  "is_approved": true,
  "original_filename": "test-file.txt",
  "file_path_stored": "uploads/test-file.txt",
  "file_path_resolved": "/path/to/uploads/test-file.txt",
  "file_exists": true,
  "file_readable": true,
  "file_size_in_db": 41,
  "file_size_on_disk": 41,
  "size_matches": true
}
```

### 3. Debug Tool
A Python script (`debug_downloads.py`) is provided to help diagnose production issues:

```bash
python debug_downloads.py https://afh.joshattic.us 1
```

This tool will:
1. Check API health status
2. Debug the specific upload ID
3. Test the actual download
4. Provide specific recommendations for fixing issues

## Usage Instructions

### For System Administrators

1. **Check API Health**:
   ```bash
   curl https://afh.joshattic.us/api/health
   ```

2. **Debug Specific Upload**:
   ```bash
   curl https://afh.joshattic.us/api/debug/upload/1
   ```

3. **Use Debug Tool**:
   ```bash
   python debug_downloads.py https://afh.joshattic.us 1
   ```

### For Developers

1. **Check Application Logs**:
   The enhanced logging will show exactly where the download process fails:
   ```
   [INFO] Download request for upload ID: 1
   [INFO] Upload found - ID: 1, Status: approved, Path: uploads/test-file.txt
   [INFO] Resolved file path: /app/uploads/test-file.txt
   [ERROR] File not found on disk: /app/uploads/test-file.txt
   ```

2. **Monitor Error Patterns**:
   - Frequent "Upload not found" → Database sync issues
   - Frequent "Upload not approved" → Approval workflow issues
   - Frequent "File not found on disk" → File storage issues

## Common Issues and Solutions

### Upload Not Found
- **Cause**: Upload ID doesn't exist in database
- **Solution**: Verify database integrity, check if upload was properly created

### Upload Not Approved
- **Cause**: Upload status is 'pending' or 'rejected'
- **Solution**: Review and approve uploads through admin interface

### File Not Found
- **Cause**: File was deleted or moved from upload directory
- **Solution**: Restore file from backup or remove invalid upload records

### File Not Readable
- **Cause**: Permission issues
- **Solution**: Fix file permissions (`chmod 644` for files, `chmod 755` for directories)

### Web Server Issues
- **Cause**: nginx/Apache not routing `/api/*` requests to Flask
- **Solution**: Verify reverse proxy configuration includes API routes

## Testing

The solution includes comprehensive tests for all error scenarios:

```python
# Test successful download
response = client.get('/api/download/1')  # Should return 200

# Test missing upload
response = client.get('/api/download/999')  # Should return 404

# Test unapproved upload
response = client.get('/api/download/3')  # Should return 404

# Test missing file
response = client.get('/api/download/2')  # Should return 404
```

## Deployment Notes

1. The enhanced error handling is backward compatible
2. New endpoints are optional but recommended for monitoring
3. Debug tool can be run from any machine with Python and `requests` library
4. No database schema changes required

## Monitoring Recommendations

1. Set up monitoring for `/api/health` endpoint
2. Monitor application logs for download error patterns
3. Use debug endpoints to investigate user-reported issues
4. Set up alerts for high 404 rates on download endpoints