# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import boto3
import os
from botocore.exceptions import ClientError
from datetime import datetime
from . import logger, config, ub

log = logger.create()

def _get_s3_config_value(db_value, env_var_name):
    """Get config value from database or environment variable"""
    if db_value:
        return db_value
    return os.environ.get(env_var_name, '')

class S3CoverManager:
    """Manages book cover storage and retrieval from S3"""
    
    def __init__(self):
        self.s3_client = None
        self.enabled = False
        self._initialize()
    
    def _initialize(self):
        """Initialize S3 client if enabled in config"""
        # Always enable S3 (hardcoded for now)
        try:
            # Get credentials from environment
            region = os.environ.get('S3_REGION', 'ap-southeast-1')
            bucket = os.environ.get('S3_BUCKET', 'cdn.mnd.vn')
            access_key = os.environ.get('S3_ACCESS_KEY', '')
            secret_key = os.environ.get('S3_SECRET_KEY', '')
            
            if not bucket or not access_key or not secret_key:
                log.warning("S3 not properly configured - missing bucket or credentials")
                return
            
            self.s3_client = boto3.client(
                's3',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
            self.enabled = True
            log.info("S3 cover manager initialized for bucket: %s (region: %s)", bucket, region)
        except Exception as e:
            log.error("Failed to initialize S3 client: %s", e)
            self.enabled = False
    
    def is_cover_in_s3(self, book_id, resolution=None):
        """
        Check if cover is tracked as uploaded to S3
        
        Args:
            book_id: Book ID
            resolution: Optional resolution string
        
        Returns:
            S3CoverUpload record or None
        """
        try:
            # Try using SQLAlchemy session first
            if ub.session:
                log.info("Using SQLAlchemy session for book %s, resolution %s", book_id, resolution)
                query = ub.session.query(ub.S3CoverUpload) \
                    .filter(ub.S3CoverUpload.book_id == book_id)
                
                # Handle both NULL and actual resolution values
                if resolution is None:
                    query = query.filter(ub.S3CoverUpload.resolution.is_(None))
                else:
                    query = query.filter(ub.S3CoverUpload.resolution == resolution)
                
                result = query.first()
                log.info("SQLAlchemy query result: %s", result)
                return result
            else:
                # Fallback to direct SQLite query
                import sqlite3
                log.info("Using SQLite fallback for book %s, resolution %s", book_id, resolution)
                
                # Get database path - try multiple locations
                db_path = ub.app_DB_path
                if not db_path:
                    # Fallback to common database locations
                    import os
                    possible_paths = [
                        '/config/app.db',
                        '/app/calibre-web-automated/config/app.db',
                        './config/app.db'
                    ]
                    for path in possible_paths:
                        if os.path.exists(path):
                            db_path = path
                            break
                
                log.info("Using database path: %s", db_path)
                if not db_path:
                    return None
                
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                if resolution is None:
                    cursor.execute("""
                        SELECT id, book_id, resolution, s3_key, uploaded_at, file_size, etag
                        FROM s3_cover_uploads
                        WHERE book_id = ? AND resolution IS NULL
                    """, (book_id,))
                else:
                    cursor.execute("""
                        SELECT id, book_id, resolution, s3_key, uploaded_at, file_size, etag
                        FROM s3_cover_uploads
                        WHERE book_id = ? AND resolution = ?
                    """, (book_id, resolution))
                
                row = cursor.fetchone()
                conn.close()
                
                log.info("SQLite query result: %s", row)
                if row:
                    # Create a mock S3CoverUpload object
                    class MockS3CoverUpload:
                        def __init__(self, row):
                            self.id = row[0]
                            self.book_id = row[1]
                            self.resolution = row[2]
                            self.s3_key = row[3]
                            self.uploaded_at = row[4]
                            self.file_size = row[5]
                            self.etag = row[6]
                    
                    result = MockS3CoverUpload(row)
                    log.info("Created MockS3CoverUpload: %s", result.s3_key)
                    return result
                
                return None
        except Exception as e:
            log.error("Error checking S3 upload tracking: %s", e)
            return None
    
    def get_cover_url(self, book_id, resolution=None):
        """
        Get S3 URL for a book cover (uses database tracking)
        
        Args:
            book_id: Book ID
            resolution: Optional resolution (sm, md, lg, og)
        
        Returns:
            Full S3/CDN URL or None if not found
        """
        if not self.enabled:
            return None
        
        # Map resolution for database lookup
        # resolution comes as constants: 0=original, 1=small, 2=medium, 4=large
        # Database stores None for original, and string values for others
        if resolution == 0:
            db_resolution = None  # Original
        elif resolution == 1:
            db_resolution = 'sm'  # Small
        elif resolution == 2:
            db_resolution = 'md'  # Medium
        elif resolution == 4:
            db_resolution = 'lg'  # Large
        else:
            db_resolution = str(resolution)  # Fallback
        log.info("Looking up S3 cover for book %s, resolution %s -> db_resolution %s", book_id, resolution, db_resolution)
        
        # Check database tracking first (fast)
        upload_record = self.is_cover_in_s3(book_id, db_resolution)
        log.info("Upload record found: %s", upload_record)
        
        if not upload_record:
            return None  # Not uploaded yet
        
        # Build URL from tracking record
        s3_key = upload_record.s3_key
        
        # Use environment variables directly
        cdn_url = os.environ.get('S3_CDN_URL', '')
        if cdn_url:
            return f"{cdn_url}/{s3_key}"
        else:
            # Use direct S3 URL format: https://s3.region.amazonaws.com/bucket/key
            bucket = os.environ.get('S3_BUCKET', 'cdn.mnd.vn')
            region = os.environ.get('S3_REGION', 'ap-southeast-1')
            return f"https://s3.{region}.amazonaws.com/{bucket}/{s3_key}"
    
    def verify_cover_exists(self, book_id, resolution=None):
        """
        Verify cover actually exists in S3 (makes HEAD request)
        Use sparingly - primarily for debugging/validation
        
        Returns:
            True if exists in S3, False otherwise
        """
        if not self.enabled:
            return False
        
        upload_record = self.is_cover_in_s3(book_id, resolution)
        if not upload_record:
            return False
        
        try:
            bucket = _get_s3_config_value(config.config_s3_bucket, 'S3_BUCKET')
            self.s3_client.head_object(
                Bucket=bucket,
                Key=upload_record.s3_key
            )
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                log.warning("Cover tracked but not found in S3: %s", upload_record.s3_key)
                # Remove stale tracking record
                ub.session.delete(upload_record)
                ub.session.commit()
            return False
    
    def upload_cover(self, book_id, cover_path, resolution=None):
        """
        Upload a cover image to S3 (with duplicate prevention)
        
        Args:
            book_id: Book ID
            Cover_path: Local path to cover file
            resolution: Optional resolution for thumbnails
        
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            log.warning("S3 not enabled, skipping upload")
            return False
        
        # Check if already uploaded
        existing = self.is_cover_in_s3(book_id, resolution)
        if existing:
            log.info("Cover already uploaded to S3: book_id=%s, resolution=%s", book_id, resolution)
            return True
        
        # Generate S3 key (stored in cw-cover folder)
        if resolution:
            s3_key = f"cw-cover/{book_id}/{resolution}.jpg"
        else:
            s3_key = f"cw-cover/{book_id}/cover.jpg"
        
        # Check if file exists locally
        if not os.path.exists(cover_path):
            log.error("Cover file not found: %s", cover_path)
            return False
        
        try:
            # Get bucket name from config or environment
            bucket = _get_s3_config_value(config.config_s3_bucket, 'S3_BUCKET')
            
            # Upload to S3
            with open(cover_path, 'rb') as cover_file:
                response = self.s3_client.put_object(
                    Bucket=bucket,
                    Key=s3_key,
                    Body=cover_file,
                    ContentType='image/jpeg',
                    CacheControl='public, max-age=31536000'  # 1 year cache
                )
            
            # Record in database
            upload_record = ub.S3CoverUpload(
                book_id=book_id,
                resolution=resolution,
                s3_key=s3_key,
                file_size=os.path.getsize(cover_path),
                etag=response['ETag']
            )
            ub.session.add(upload_record)
            ub.session.commit()
            
            log.info("Successfully uploaded cover to S3: %s", s3_key)
            return True
        
        except Exception as e:
            log.error("Failed to upload cover to S3: %s", e)
            return False

# Singleton instance
_s3_manager = None

def get_s3_manager():
    """Get singleton S3 manager instance"""
    global _s3_manager
    if _s3_manager is None:
        log.debug("Creating new S3CoverManager instance")
        _s3_manager = S3CoverManager()
    else:
        log.debug("Returning existing S3CoverManager instance")
    return _s3_manager

