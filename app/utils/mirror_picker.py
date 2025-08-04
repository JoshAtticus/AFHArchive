"""
AFHArchive Mirror Picker Service
Intelligently selects the best mirror for file downloads
"""

import requests
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from app.models import Mirror, Upload, MirrorFile
from app import db
from flask import current_app, request


class MirrorPicker:
    """Service for selecting the best mirror for downloads"""
    
    def __init__(self):
        self.main_server_priority = 1000  # High priority for main server
        self.cache_duration = 300  # 5 minutes cache for mirror health
        self._health_cache = {}
    
    def get_best_mirror_for_download(self, upload_id: int, user_ip: str = None) -> Dict[str, Any]:
        """
        Get the best mirror for downloading a specific file
        
        Args:
            upload_id: The upload ID to download
            user_ip: User's IP address for geo-routing (optional, will auto-detect if not provided)
            
        Returns:
            Dict with mirror info and download URL
        """
        upload = Upload.query.get(upload_id)
        if not upload or upload.status != 'approved':
            return None
        
        # Auto-detect user IP if not provided
        if user_ip is None:
            user_ip = self._get_user_ip()
        
        # Get all mirrors that have this file
        available_mirrors = self._get_available_mirrors_for_file(upload_id)
        
        # Always include main server as an option
        main_server_mirror = self._get_main_server_mirror()
        available_mirrors.append(main_server_mirror)
        
        # Filter out unhealthy mirrors
        healthy_mirrors = self._filter_healthy_mirrors(available_mirrors)
        
        if not healthy_mirrors:
            # Fallback to main server
            return self._create_download_response(main_server_mirror, upload_id, is_fallback=True)
        
        # Select best mirror based on various factors
        best_mirror = self._select_best_mirror(healthy_mirrors, user_ip)
        
        return self._create_download_response(best_mirror, upload_id)
    
    def _get_user_ip(self) -> str:
        """Extract user's real IP address from request headers"""
        # Check X-Forwarded-For header first (most common for proxies/load balancers)
        x_forwarded_for = request.headers.get('X-Forwarded-For')
        if x_forwarded_for:
            # X-Forwarded-For can contain multiple IPs, the first one is the original client
            return x_forwarded_for.split(',')[0].strip()
        
        # Check other common proxy headers
        x_real_ip = request.headers.get('X-Real-IP')
        if x_real_ip:
            return x_real_ip.strip()
        
        # Check CF-Connecting-IP (Cloudflare)
        cf_connecting_ip = request.headers.get('CF-Connecting-IP')
        if cf_connecting_ip:
            return cf_connecting_ip.strip()
        
        # Check X-Forwarded header (less common)
        x_forwarded = request.headers.get('X-Forwarded')
        if x_forwarded:
            # X-Forwarded: for=192.168.1.1
            if 'for=' in x_forwarded:
                return x_forwarded.split('for=')[1].split(',')[0].strip()
        
        # Fallback to direct remote address
        return request.remote_addr or '127.0.0.1'
    
    def _get_available_mirrors_for_file(self, upload_id: int) -> List[Dict[str, Any]]:
        """Get all mirrors that have the specified file"""
        mirrors_with_file = db.session.query(Mirror, MirrorFile).join(
            MirrorFile, Mirror.id == MirrorFile.mirror_id
        ).filter(MirrorFile.upload_id == upload_id).all()
        
        available_mirrors = []
        for mirror, mirror_file in mirrors_with_file:
            mirror_info = {
                'id': mirror.id,
                'name': mirror.name,
                'type': 'mirror',
                'direct_url': mirror.direct_url,
                'cloudflare_url': mirror.cloudflare_url,
                'last_seen': mirror.last_seen,
                'priority': self._calculate_mirror_priority(mirror),
                'has_file': True
            }
            available_mirrors.append(mirror_info)
        
        return available_mirrors
    
    def _get_main_server_mirror(self) -> Dict[str, Any]:
        """Get main server as a mirror option"""
        return {
            'id': 'main',
            'name': 'Main Server',
            'type': 'main',
            'direct_url': 'localhost',  # Will be replaced with actual server URL
            'cloudflare_url': None,
            'last_seen': datetime.utcnow(),
            'priority': self.main_server_priority,
            'has_file': True  # Main server always has all approved files
        }
    
    def _filter_healthy_mirrors(self, mirrors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out unhealthy mirrors"""
        healthy_mirrors = []
        
        for mirror in mirrors:
            if mirror['type'] == 'main':
                # Main server is always considered healthy
                healthy_mirrors.append(mirror)
                continue
            
            # Check if mirror is healthy
            if self._is_mirror_healthy(mirror):
                healthy_mirrors.append(mirror)
        
        return healthy_mirrors
    
    def _is_mirror_healthy(self, mirror: Dict[str, Any]) -> bool:
        """Check if a mirror is healthy (cached for performance)"""
        mirror_id = mirror['id']
        current_time = time.time()
        
        # Check cache first
        if mirror_id in self._health_cache:
            cached_result, cached_time = self._health_cache[mirror_id]
            if current_time - cached_time < self.cache_duration:
                return cached_result
        
        # Perform health check
        is_healthy = self._perform_health_check(mirror)
        
        # Cache the result
        self._health_cache[mirror_id] = (is_healthy, current_time)
        
        return is_healthy
    
    def _perform_health_check(self, mirror: Dict[str, Any]) -> bool:
        """Perform actual health check on mirror"""
        try:
            # Check if mirror was seen recently
            if mirror['last_seen']:
                time_since_seen = datetime.utcnow() - mirror['last_seen']
                if time_since_seen > timedelta(minutes=10):
                    return False
            
            # Try to reach the mirror
            health_url = f"http://{mirror['direct_url']}/health"
            response = requests.get(health_url, timeout=5)
            return response.status_code == 200
            
        except Exception as e:
            current_app.logger.warning(f"Health check failed for mirror {mirror['name']}: {e}")
            return False
    
    def _select_best_mirror(self, mirrors: List[Dict[str, Any]], user_ip: str = None) -> Dict[str, Any]:
        """Select the best mirror based on various factors"""
        # Sort mirrors by priority and other factors
        scored_mirrors = []
        
        for mirror in mirrors:
            score = self._calculate_mirror_score(mirror, user_ip)
            scored_mirrors.append((score, mirror))
        
        # Sort by score (higher is better)
        scored_mirrors.sort(key=lambda x: x[0], reverse=True)
        
        # Return the best mirror
        return scored_mirrors[0][1] if scored_mirrors else None
    
    def _calculate_mirror_score(self, mirror: Dict[str, Any], user_ip: str = None) -> float:
        """Calculate a score for mirror selection"""
        score = 0.0
        
        # Base priority
        score += mirror['priority']
        
        # Geographic proximity (if user IP is available)
        if user_ip and mirror['type'] != 'main':
            geo_score = self._calculate_geo_score(mirror, user_ip)
            score += geo_score
        
        # Mirror load (prefer less loaded mirrors)
        if mirror['type'] != 'main':
            load_score = self._calculate_load_score(mirror)
            score += load_score
        
        # Cloudflare bonus (better performance)
        if mirror.get('cloudflare_url'):
            score += 100
        
        return score
    
    def _calculate_mirror_priority(self, mirror) -> int:
        """Calculate base priority for a mirror"""
        priority = 100  # Base priority
        
        # Bonus for recently seen mirrors
        if mirror.last_seen:
            time_since_seen = datetime.utcnow() - mirror.last_seen
            if time_since_seen < timedelta(minutes=5):
                priority += 50
            elif time_since_seen < timedelta(hours=1):
                priority += 25
        
        return priority
    
    def _calculate_geo_score(self, mirror: Dict[str, Any], user_ip: str) -> float:
        """Calculate geographic proximity score (simplified implementation)"""
        # Simple scoring based on mirror priority since we don't have GeoIP
        # In production, you could implement simple region-based routing
        # or integrate with a different geolocation service
        return 50.0  # Default score for all mirrors
    
    def _calculate_load_score(self, mirror: Dict[str, Any]) -> float:
        """Calculate load-based score (prefer less loaded mirrors)"""
        # This is a placeholder - in production you'd check actual mirror load
        # TODO: Implement proper load monitoring
        return 25.0
    
    def _create_download_response(self, mirror: Dict[str, Any], upload_id: int, is_fallback: bool = False) -> Dict[str, Any]:
        """Create download response with mirror information"""
        if mirror['type'] == 'main':
            download_url = f"/download/{upload_id}"
            server_name = "Main Server"
        else:
            # Prefer Cloudflare URL if available
            if mirror.get('cloudflare_url'):
                download_url = f"{mirror['cloudflare_url']}/download/{upload_id}"
                server_name = f"{mirror['name']} (CDN)"
            else:
                download_url = f"http://{mirror['direct_url']}/download/{upload_id}"
                server_name = mirror['name']
        
        return {
            'mirror_id': mirror['id'],
            'mirror_name': mirror['name'],
            'server_name': server_name,
            'download_url': download_url,
            'mirror_type': mirror['type'],
            'is_fallback': is_fallback,
            'cloudflare_enabled': bool(mirror.get('cloudflare_url'))
        }
    
    def get_mirror_statistics(self) -> Dict[str, Any]:
        """Get statistics about mirror usage"""
        total_mirrors = Mirror.query.count()
        online_mirrors = Mirror.query.filter(
            Mirror.last_seen > datetime.utcnow() - timedelta(minutes=5)
        ).count()
        
        return {
            'total_mirrors': total_mirrors,
            'online_mirrors': online_mirrors,
            'main_server_available': True,
            'health_cache_size': len(self._health_cache)
        }


# Global instance
mirror_picker = MirrorPicker()
