#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bulk upload script for Calibre-Web-Automated covers to S3
"""

import os
import sys
import argparse
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from cps import calibre_db, config, logger
from cps.s3_cover import get_s3_manager
from cps import fs
from cps.constants import CACHE_TYPE_THUMBNAILS

log = logger.create()

def get_book_cover_thumbnail_by_format(book, resolution, format):
    """Import and use existing thumbnail getter"""
    from cps.helper import get_book_cover_thumbnail_by_format as _getter
    return _getter(book, resolution, format)

def main():
    parser = argparse.ArgumentParser(description='Upload Calibre covers to S3')
    parser.add_argument('--book-id', type=int, help='Upload covers for specific book ID')
    parser.add_argument('--all', action='store_true', help='Upload all covers')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be uploaded without actually uploading')
    parser.add_argument('--force', action='store_true', help='Force re-upload even if already in S3')
    
    args = parser.parse_args()
    
    if not config.config_s3_enabled:
        log.error("S3 is not enabled in configuration")
        return 1
    
    s3_manager = get_s3_manager()
    if not s3_manager.enabled:
        log.error("S3 manager not initialized")
        return 1
    
    calibre_path = config.get_book_path()
    
    if args.book_id:
        # Upload specific book
        log.info("Uploading covers for book ID: %s", args.book_id)
        
        book = calibre_db.get_book(args.book_id)
        if not book:
            log.error("Book with ID %s not found", args.book_id)
            return 1
        
        if not book.has_cover:
            log.warning("Book %s has no cover", args.book_id)
            return 0
        
        if args.dry_run:
            log.info("DRY RUN: Would upload covers for book %s", args.book_id)
            return 0
        
        # Upload original cover
        cover_path = os.path.join(calibre_path, book.path, "cover.jpg")
        if os.path.exists(cover_path):
            if args.force or not s3_manager.is_cover_in_s3(args.book_id):
                result = s3_manager.upload_cover(args.book_id, cover_path)
                log.info("Original cover upload result: %s", "success" if result else "failed")
        
        # Upload thumbnails if they exist
        cache = fs.FileSystem()
        for resolution in ['sm', 'md', 'lg']:
            webp_thumb = get_book_cover_thumbnail_by_format(book, resolution, 'webp')
            jpg_thumb = get_book_cover_thumbnail_by_format(book, resolution, 'jpg')
            
            thumbnail_to_upload = webp_thumb if webp_thumb else jpg_thumb
            
            if thumbnail_to_upload:
                thumb_path = cache.get_cache_file_path(thumbnail_to_upload.filename, CACHE_TYPE_THUMBNAILS)
                if os.path.exists(thumb_path):
                    if args.force or not s3_manager.is_cover_in_s3(args.book_id, resolution):
                        result = s3_manager.upload_cover(args.book_id, thumb_path, resolution)
                        log.info("Thumbnail %s upload result: %s", resolution, "success" if result else "failed")
        
    elif args.all:
        # Upload all books
        log.info("Starting bulk upload of all covers...")
        
        books = calibre_db.session.query(calibre_db.Books).filter(calibre_db.Books.has_cover == 1).all()
        log.info("Found %d books with covers", len(books))
        
        uploaded_count = 0
        skipped_count = 0
        
        for book in books:
            if args.dry_run:
                log.info("DRY RUN: Would upload covers for book %s (%s)", book.id, book.title)
                continue
            
            # Check if already uploaded (unless force)
            if not args.force and s3_manager.is_cover_in_s3(book.id):
                log.debug("Skipping book %s - already uploaded", book.id)
                skipped_count += 1
                continue
            
            # Upload original cover
            cover_path = os.path.join(calibre_path, book.path, "cover.jpg")
            if os.path.exists(cover_path):
                s3_manager.upload_cover(book.id, cover_path)
            
            # Upload thumbnails
            cache = fs.FileSystem()
            for resolution in ['sm', 'md', 'lg']:
                webp_thumb = get_book_cover_thumbnail_by_format(book, resolution, 'webp')
                jpg_thumb = get_book_cover_thumbnail_by_format(book, resolution, 'jpg')
                
                thumbnail_to_upload = webp_thumb if webp_thumb else jpg_thumb
                
                if thumbnail_to_upload:
                    thumb_path = cache.get_cache_file_path(thumbnail_to_upload.filename, CACHE_TYPE_THUMBNAILS)
                    if os.path.exists(thumb_path):
                        s3_manager.upload_cover(book.id, thumb_path, resolution)
            
            uploaded_count += 1
            if uploaded_count % 10 == 0:
                log.info("Progress: %d/%d books processed", uploaded_count, len(books))
        
        if not args.dry_run:
            log.info("Bulk upload complete: %d uploaded, %d skipped", uploaded_count, skipped_count)
        else:
            log.info("DRY RUN complete: Would upload %d books", len(books))
    
    else:
        parser.print_help()
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())

