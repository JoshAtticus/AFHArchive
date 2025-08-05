# AFHArchive Mirror System

The AFHArchive Mirror System allows you to deploy distributed file servers that automatically sync with the main server to provide faster downloads for users around the world.

## Overview

The mirror system consists of:

- **Main Server**: Handles uploads, approval, and distributes files to mirrors
- **Mirror Servers**: Store and serve files to users, sync automatically with main server
- **Pairing System**: Secure way to connect mirrors to the main server
- **Management Interface**: Web-based admin panel for managing mirrors

## Features

- 🌍 **Global Distribution**: Deploy mirrors worldwide for faster downloads
- 🔄 **Automatic Synchronization**: Files sync automatically based on popularity
- 📊 **Intelligent Caching**: Most popular files are prioritized
- 🔐 **Secure Pairing**: Temporary codes for secure mirror registration
- 📈 **Real-time Monitoring**: View mirror status, logs, and performance
- ☁️ **Cloudflare Support**: Optional Cloudflare Tunnel integration
- 💾 **Flexible Storage**: Custom storage paths for VM setups

## Quick Start

### Setting Up a Mirror Server

1. **Download the mirror script**:
   ```bash
   wget https://afharchive.xyz/mirror.py
   # OR copy from the main server repository
   ```

2. **Run the setup**:
   ```bash
   python mirror.py setup
   ```

3. **Configure the mirror** (edit `.env`):
   ```env
   MAIN_SERVER_URL=https://afharchive.xyz
   MIRROR_NAME=Frankfurt Germany
   MIRROR_PORT=5000
   STORAGE_PATH=mirror_uploads
   MAX_FILES=1000
   ```

4. **Start the mirror server**:
   ```bash
   python mirror.py
   ```

5. **Auto-registration**: The mirror will automatically register with the main server

6. **Admin approval**: An admin will approve your mirror in the admin panel at `/admin/mirrors`

### Managing Mirrors (Admin)

1. **Access the admin panel**: `/admin/mirrors`
2. **Approve pending mirrors**: Review and approve new mirror registrations
3. **Monitor mirrors**: View status, files, and sync logs
4. **Configure mirrors**: Edit settings like max files and URLs
5. **Trigger syncs**: Manually start synchronization

## Architecture

### Main Server Components

- **Mirror Models**: Database tables for mirrors, files, and logs
- **Mirror API**: REST endpoints for mirror communication
- **Admin Interface**: Web UI for mirror management
- **Sync Engine**: Background task for file distribution

### Mirror Server Components

- **Flask Server**: Lightweight web server for API and file serving
- **Local Database**: SQLite for tracking stored files
- **Sync Client**: Automatic synchronization with main server
- **File Storage**: Local file system or custom paths

## Configuration

### Main Server Configuration

Add to your main server's `.env`:
```env
# Mirror system is automatically enabled
# No additional configuration needed
```

### Mirror Server Configuration

Edit the mirror's `.env` file:

```env
# Required Settings
MAIN_SERVER_URL=https://afharchive.xyz
MIRROR_NAME=My Mirror Server
MIRROR_PORT=5000

# Storage Settings
STORAGE_PATH=mirror_uploads
MAX_FILES=1000

# Optional: Custom storage path for VMs
# STORAGE_PATH=/mnt/block-storage/mirror

# Optional: Cloudflare Tunnel URL
# CLOUDFLARE_URL=https://mirror.afharchive.xyz

# Advanced Settings
# MIRROR_LOG_LEVEL=INFO
# SYNC_INTERVAL=300
# HEARTBEAT_INTERVAL=60
```

## Production Deployment

### Mirror Server Setup

1. **Install as a service**:
   ```bash
   # Copy the generated service file
   sudo cp afharchive-mirror.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable afharchive-mirror
   sudo systemctl start afharchive-mirror
   ```

2. **Configure firewall**:
   ```bash
   sudo ufw allow 5000/tcp
   ```

3. **Set up reverse proxy** (nginx example):
   ```nginx
   server {
       listen 80;
       server_name mirror.afharchive.xyz;
       
       location / {
           proxy_pass http://localhost:5000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

4. **Configure Cloudflare Tunnel** (optional):
   ```bash
   cloudflared tunnel create afharchive-mirror
   cloudflared tunnel route dns afharchive-mirror mirror.afharchive.xyz
   ```

### Security Considerations

- **API Keys**: Each mirror has a unique API key for authentication
- **Firewall**: Restrict access to mirror management ports
- **HTTPS**: Use SSL/TLS for all communication
- **Monitoring**: Set up alerts for mirror downtime

## API Reference

### Mirror Server Endpoints

#### Health Check
```http
GET /health
```
Returns mirror status and basic information.

#### Pairing
```http
POST /pair
Content-Type: application/json

{
  "pairing_code": "ABC123456",
  "direct_url": "mirror.example.com:5000",
  "cloudflare_url": "https://mirror.afharchive.xyz"
}
```

#### File Download
```http
GET /download/{upload_id}
```
Download a specific file from the mirror.

### Main Server API Endpoints

#### Mirror Management
```http
GET /api/mirrors/{mirror_id}/status
Authorization: Bearer {admin_token}
```

#### Trigger Sync
```http
POST /api/mirrors/{mirror_id}/trigger-sync
Authorization: Bearer {admin_token}
```

## Monitoring and Troubleshooting

### Mirror Logs

Monitor mirror server logs:
```bash
tail -f mirror.log
```

### Main Server Logs

Check sync logs in the admin panel:
- Go to `/admin/mirrors`
- Click on a mirror to view detailed logs
- Check the "Recent Sync Activity" section

### Common Issues

1. **Mirror shows as offline**:
   - Check network connectivity
   - Verify firewall settings
   - Check mirror server logs

2. **Files not syncing**:
   - Verify API key is correct
   - Check storage space on mirror
   - Review sync logs for errors

3. **Pairing fails**:
   - Ensure pairing code hasn't expired
   - Check that the code hasn't been used already
   - Verify network connectivity between servers

### Health Checks

Run the test script to verify functionality:
```bash
python test_mirror_system.py
```

## Storage Management

### File Priority

Files are distributed to mirrors based on:
1. **Download count** (most popular first)
2. **File size** (smaller files preferred when space is limited)
3. **Upload date** (newer files preferred)

### Storage Limits

- Set `MAX_FILES` to control how many files each mirror stores
- System automatically manages file rotation
- Popular files are kept, less popular files are removed

### Custom Storage Paths

For VM deployments with block storage:
```env
STORAGE_PATH=/mnt/block-storage/mirror
```

Ensure the path exists and is writable:
```bash
sudo mkdir -p /mnt/block-storage/mirror
sudo chown afharchive:afharchive /mnt/block-storage/mirror
```

## Performance Tuning

### Mirror Server

- **Worker Processes**: Adjust gunicorn workers for your CPU count
- **Disk I/O**: Use SSD storage for better performance
- **Network**: Ensure adequate bandwidth for file transfers

### Main Server

- **Sync Frequency**: Adjust sync intervals based on upload frequency
- **Database**: Regular maintenance for optimal performance
- **Monitoring**: Set up metrics collection for insights

## Contributing

The mirror system is part of the AFHArchive project. To contribute:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

This mirror system is part of AFHArchive and follows the same license terms.

## Support

For support with the mirror system:

1. Check the troubleshooting section above
2. Review the logs for error messages
3. Open an issue on the AFHArchive repository
4. Contact the project maintainers

---

*AFHArchive Mirror System - Distributed file serving made simple*
