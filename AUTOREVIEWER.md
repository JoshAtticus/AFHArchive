# AFHArchive Autoreviewer System

The AFHArchive Autoreviewer is an automated system that helps manage duplicate file uploads by automatically rejecting files that have already been uploaded to the archive.

## How It Works

1. **Automatic Detection**: When a user uploads a file, the autoreviewer automatically checks the MD5 hash against existing files
2. **Duplicate Rejection**: If a duplicate is found (matching MD5 hash), the upload is automatically rejected
3. **User Notification**: The uploader receives an email notification explaining the rejection with details about the existing file
4. **Admin Visibility**: The autoreviewer appears as "AFH Autoreviewer" in the admin interface

## Features

- **Real-time Processing**: Runs immediately after each file upload
- **MD5 Hash Comparison**: Uses cryptographic hashes to detect exact file duplicates
- **Detailed Rejection Reasons**: Provides information about the existing duplicate file
- **Email Notifications**: Automatically notifies uploaders about rejections
- **Admin Dashboard**: Comprehensive management interface for monitoring autoreviewer activity
- **Batch Processing**: Ability to run autoreviewer on all pending uploads at once

## Admin Management

### Accessing the Autoreviewer Dashboard

1. Log in as an admin
2. Go to the Admin Dashboard
3. Click on "Autoreviewer" in the Quick Actions section

### Autoreviewer Dashboard Features

- **System Information**: View autoreviewer user details and status
- **Statistics**: See total reviewed uploads, rejection counts, and rejection rates
- **Batch Processing**: Run autoreviewer on all pending uploads manually
- **Recent Activity**: View recently rejected duplicate uploads

### Running Batch Processing

The batch processing feature allows you to run the autoreviewer on all pending uploads at once:

1. Go to the Autoreviewer Dashboard
2. Click "Run Batch Autoreviewer"
3. Confirm the action when prompted
4. The system will process all pending uploads and reject any duplicates found

## Technical Details

### System User

The autoreviewer operates through a special system user:
- **Name**: AFH Autoreviewer
- **Email**: autoreviewer@afharchive.system
- **Admin Status**: Yes (required for review permissions)
- **Created**: Automatically on first use

### Duplicate Detection Logic

1. **Hash Comparison**: Compares MD5 hashes of uploaded files
2. **Status Check**: Only considers files with 'approved' or 'pending' status as potential duplicates
3. **Self-Exclusion**: Excludes the current upload from comparison to avoid false positives

### Rejection Process

When a duplicate is detected:
1. Upload status is changed to 'rejected'
2. A detailed rejection reason is added including:
   - Information about the existing duplicate
   - Upload ID and filename of the duplicate
   - Current status of the duplicate
3. Review timestamp and reviewer ID are set
4. Email notification is scheduled for the uploader

## Setup and Migration

### Initial Setup

To set up the autoreviewer system:

```bash
python migrate_autoreviewer.py
```

This script will:
- Create the autoreviewer system user if it doesn't exist
- Verify the system is working correctly
- Display current statistics

### Testing

To test the autoreviewer functionality:

```bash
python test_autoreviewer.py
```

This script will:
- Verify the autoreviewer user exists
- Check for pending uploads
- Test duplicate detection logic
- Display statistics about autoreviewer activity

## Email Notifications

The autoreviewer uses the existing email notification system:
- **Template**: Uses the standard rejection email template
- **Batching**: Notifications are batched for 5 minutes before sending
- **Content**: Includes the detailed rejection reason with duplicate information

## Monitoring

### Admin Dashboard Metrics

- **Total Reviewed**: Number of uploads processed by autoreviewer
- **Total Rejected**: Number of duplicates rejected
- **Rejection Rate**: Percentage of uploads rejected as duplicates
- **Recent Activity**: List of recently rejected uploads

### Log Files

The autoreviewer logs all activity:
- Successful duplicate detections and rejections
- Non-duplicate uploads that passed review
- Errors during processing

## Best Practices

1. **Regular Monitoring**: Check the autoreviewer dashboard regularly for statistics
2. **Batch Processing**: Run batch processing periodically to catch any missed duplicates
3. **User Communication**: The rejection emails provide clear information to users about why their upload was rejected

## Troubleshooting

### Common Issues

1. **Autoreviewer User Missing**: Run `python migrate_autoreviewer.py` to create the system user
2. **No Activity**: Check that the autoreviewer import is working in the upload route
3. **False Positives**: The MD5 hash comparison is exact - files with identical hashes are truly identical

### Debug Information

- Check application logs for autoreviewer activity
- Use the test script to verify functionality
- Monitor the admin dashboard for statistics

## Future Enhancements

Potential improvements to the autoreviewer system:
- **File Content Analysis**: Beyond MD5, analyze file metadata
- **Filename Similarity**: Detect potential duplicates with different hashes
- **User Reputation**: Consider user history in automated decisions
- **Machine Learning**: Use ML to detect more sophisticated duplicates
