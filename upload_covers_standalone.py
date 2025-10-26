#!/usr/bin/env python3
"""
Standalone script to upload Calibre covers to S3
This script can run independently without the full Calibre-Web-Automated application
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path

# Try to import required packages, install if missing
required_packages = ['boto3', 'Pillow']
missing_packages = []

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    missing_packages.append('boto3')

try:
    from PIL import Image
except ImportError:
    missing_packages.append('Pillow')

if missing_packages:
    print(f"❌ Missing packages: {', '.join(missing_packages)}. Installing...")
    import subprocess
    try:
        for package in missing_packages:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print("✅ All packages installed successfully")
        # Re-import after installation
        import boto3
        from botocore.exceptions import ClientError
        from PIL import Image
    except subprocess.CalledProcessError:
        print("❌ Failed to install required packages. Please install them manually:")
        print("   pip install boto3 Pillow")
        sys.exit(1)

# S3 Configuration - must be provided via environment variables or command line
S3_BUCKET = os.environ.get('S3_BUCKET', '')
S3_REGION = os.environ.get('S3_REGION', 'us-east-1')
S3_ACCESS_KEY = os.environ.get('S3_ACCESS_KEY', '')
S3_SECRET_KEY = os.environ.get('S3_SECRET_KEY', '')

# Thumbnail sizes (matching Calibre-Web constants)
THUMBNAIL_SIZES = {
    'sm': 200,   # Small
    'md': 400,   # Medium  
    'lg': 800,   # Large
}

def generate_thumbnail(image_path, size, output_path):
    """Generate a thumbnail of the specified size"""
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary (handles RGBA, P mode images)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Calculate thumbnail size maintaining aspect ratio
            img.thumbnail((size, size), Image.Resampling.LANCZOS)
            
            # Save as JPEG
            img.save(output_path, 'JPEG', quality=85, optimize=True)
            return True
    except Exception as e:
        print(f"  ❌ Failed to generate {size}px thumbnail: {e}")
        return False

def generate_all_thumbnails(cover_path, book_id, temp_dir):
    """Generate all thumbnail sizes for a book cover"""
    thumbnails = {}
    
    # Generate thumbnails for each size
    for resolution, size in THUMBNAIL_SIZES.items():
        thumb_path = os.path.join(temp_dir, f"cover_{resolution}_{book_id}.jpg")
        if generate_thumbnail(cover_path, size, thumb_path):
            thumbnails[resolution] = thumb_path
            print(f"  📐 Generated {resolution} thumbnail ({size}px)")
        else:
            print(f"  ⚠️  Skipped {resolution} thumbnail")
    
    return thumbnails

def get_books_with_covers(metadata_db_path):
    """Get all books that have covers from Calibre metadata.db"""
    conn = sqlite3.connect(metadata_db_path)
    cursor = conn.cursor()
    
    # Query books with covers
    cursor.execute("""
        SELECT id, path, title 
        FROM books 
        WHERE has_cover = 1
        ORDER BY id
    """)
    
    books = cursor.fetchall()
    conn.close()
    return books

def is_cover_already_uploaded(book_id, resolution=None):
    """Check if cover is already tracked as uploaded for specific resolution"""
    try:
        # Try multiple possible database locations
        possible_paths = [
            "./config/app.db",  # Current directory
            os.path.expanduser("~/calibre-web-automated/config/app.db"),  # Home directory
            os.path.join(os.path.dirname(__file__), "config", "app.db"),  # Script directory
        ]
        
        cwa_db_path = None
        for path in possible_paths:
            if os.path.exists(path):
                cwa_db_path = path
                break
        
        if not cwa_db_path:
            return False
        
        conn = sqlite3.connect(cwa_db_path)
        cursor = conn.cursor()
        
        if resolution is None:
            # Check for original cover
            cursor.execute("""
                SELECT COUNT(*) FROM s3_cover_uploads
                WHERE book_id = ? AND resolution IS NULL
            """, (book_id,))
        else:
            # Check for specific resolution
            cursor.execute("""
                SELECT COUNT(*) FROM s3_cover_uploads
                WHERE book_id = ? AND resolution = ?
            """, (book_id, resolution))
        
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False

def get_uploaded_resolutions(book_id):
    """Get list of already uploaded resolutions for a book"""
    try:
        possible_paths = [
            "./config/app.db",
            os.path.expanduser("~/calibre-web-automated/config/app.db"),
            os.path.join(os.path.dirname(__file__), "config", "app.db"),
        ]
        
        cwa_db_path = None
        for path in possible_paths:
            if os.path.exists(path):
                cwa_db_path = path
                break
        
        if not cwa_db_path:
            return []
        
        conn = sqlite3.connect(cwa_db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT resolution FROM s3_cover_uploads
            WHERE book_id = ?
        """, (book_id,))
        
        resolutions = [row[0] for row in cursor.fetchall()]
        conn.close()
        return resolutions
    except Exception:
        return []

def upload_cover_to_s3(s3_client, bucket, book_id, cover_path, dry_run=False, force=False):
    """Upload a cover and all thumbnails to S3"""
    import tempfile
    import shutil
    
    # Create temporary directory for thumbnails
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Check what's already uploaded
        uploaded_resolutions = get_uploaded_resolutions(book_id) if not force else []
        
        # Upload original cover
        success_count = 0
        total_count = 0
        
        # Upload original cover
        if not is_cover_already_uploaded(book_id, None) or force:
            total_count += 1
            if upload_single_cover(s3_client, bucket, book_id, cover_path, None, dry_run):
                success_count += 1
        
        # Generate and upload thumbnails
        thumbnails = generate_all_thumbnails(cover_path, book_id, temp_dir)
        
        for resolution, thumb_path in thumbnails.items():
            if not is_cover_already_uploaded(book_id, resolution) or force:
                total_count += 1
                if upload_single_cover(s3_client, bucket, book_id, thumb_path, resolution, dry_run):
                    success_count += 1
        
        print(f"  📊 Uploaded {success_count}/{total_count} covers for book {book_id}")
        return success_count == total_count
        
    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)

def upload_single_cover(s3_client, bucket, book_id, cover_path, resolution, dry_run=False):
    """Upload a single cover file to S3"""
    if resolution is None:
        s3_key = f"cw-cover/{book_id}/cover.jpg"
        resolution_name = "original"
    else:
        s3_key = f"cw-cover/{book_id}/cover_{resolution}.jpg"
        resolution_name = f"{resolution} thumbnail"
    
    if dry_run:
        print(f"  [DRY RUN] Would upload: {cover_path} -> s3://{bucket}/{s3_key}")
        return True
    
    try:
        with open(cover_path, 'rb') as cover_file:
            response = s3_client.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=cover_file,
                ContentType='image/jpeg',
                CacheControl='public, max-age=31536000'
            )
        
        size = os.path.getsize(cover_path)
        etag = response['ETag'].strip('"')
        print(f"  ✅ Uploaded {resolution_name}: s3://{bucket}/{s3_key} ({size/1024:.1f} KB)")
        
        # Create database tracking record
        create_s3_tracking_record(book_id, s3_key, size, etag, resolution)
        
        return True
    except Exception as e:
        print(f"  ❌ Failed to upload {resolution_name}: {e}")
        return False

def create_s3_tracking_record(book_id, s3_key, file_size, etag, resolution=None):
    """Create tracking record in CWA database"""
    try:
        # Try multiple possible database locations
        possible_paths = [
            "./config/app.db",  # Current directory
            os.path.expanduser("~/calibre-web-automated/config/app.db"),  # Home directory
            os.path.join(os.path.dirname(__file__), "config", "app.db"),  # Script directory
        ]
        
        cwa_db_path = None
        for path in possible_paths:
            if os.path.exists(path):
                cwa_db_path = path
                break
        
        if not cwa_db_path:
            print(f"  ⚠️  CWA database not found in any expected location")
            return False
        
        conn = sqlite3.connect(cwa_db_path)
        cursor = conn.cursor()
        
        # Insert tracking record
        cursor.execute("""
            INSERT OR REPLACE INTO s3_cover_uploads
            (book_id, resolution, s3_key, uploaded_at, file_size, etag)
            VALUES (?, ?, ?, datetime('now'), ?, ?)
        """, (book_id, resolution, s3_key, file_size, etag))
        
        conn.commit()
        conn.close()
        resolution_name = "original" if resolution is None else f"{resolution} thumbnail"
        print(f"  📝 Created tracking record for book {book_id} ({resolution_name})")
        return True
        
    except Exception as e:
        print(f"  ⚠️  Failed to create tracking record: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Upload Calibre covers to S3')
    parser.add_argument('--library-path', default='~/calibre-web', 
                       help='Path to Calibre library (default: ~/calibre-web)')
    parser.add_argument('--book-id', type=int, help='Upload cover for specific book ID')
    parser.add_argument('--all', action='store_true', help='Upload all covers')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be uploaded without actually uploading')
    parser.add_argument('--force', action='store_true', help='Force re-upload even if already in S3')
    
    # S3 Configuration arguments
    parser.add_argument('--s3-bucket', help='S3 bucket name (required if not in env)')
    parser.add_argument('--s3-region', help='S3 region (default: us-east-1)')
    parser.add_argument('--s3-access-key', help='S3 access key (required if not in env)')
    parser.add_argument('--s3-secret-key', help='S3 secret key (required if not in env)')
    
    args = parser.parse_args()
    
    # Override S3 config with command line arguments
    global S3_BUCKET, S3_REGION, S3_ACCESS_KEY, S3_SECRET_KEY
    if args.s3_bucket:
        S3_BUCKET = args.s3_bucket
    if args.s3_region:
        S3_REGION = args.s3_region
    if args.s3_access_key:
        S3_ACCESS_KEY = args.s3_access_key
    if args.s3_secret_key:
        S3_SECRET_KEY = args.s3_secret_key
    
    # Validate S3 configuration
    if not S3_BUCKET or not S3_ACCESS_KEY or not S3_SECRET_KEY:
        print("❌ S3 configuration incomplete. Please provide:")
        print("   - S3_BUCKET environment variable or --s3-bucket argument")
        print("   - S3_ACCESS_KEY environment variable or --s3-access-key argument")
        print("   - S3_SECRET_KEY environment variable or --s3-secret-key argument")
        return 1
    
    # Expand library path
    library_path = os.path.expanduser(args.library_path)
    metadata_db_path = os.path.join(library_path, 'metadata.db')
    
    if not os.path.exists(metadata_db_path):
        print(f"❌ Calibre library not found: {metadata_db_path}")
        print(f"   Please check the library path: {library_path}")
        return 1
    
    print(f"📚 Using Calibre library: {library_path}")
    print(f"☁️  S3 Configuration: {S3_BUCKET} ({S3_REGION})")
    print(f"📐 Thumbnail sizes: {', '.join([f'{k}={v}px' for k, v in THUMBNAIL_SIZES.items()])}")
    
    # Initialize S3 client
    try:
        s3_client = boto3.client(
            's3',
            region_name=S3_REGION,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY
        )
        # Test S3 connection
        s3_client.head_bucket(Bucket=S3_BUCKET)
        print(f"✅ S3 connection successful")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            print(f"❌ S3 bucket not found: {S3_BUCKET}")
        elif error_code == '403':
            print(f"❌ Access denied to S3 bucket: {S3_BUCKET}")
        else:
            print(f"❌ S3 error: {e}")
        return 1
    except Exception as e:
        print(f"❌ Failed to initialize S3 client: {e}")
        return 1
    
    # Get books with covers
    books = get_books_with_covers(metadata_db_path)
    print(f"📖 Found {len(books)} books with covers")
    
    if args.book_id:
        # Upload specific book
        book = next((b for b in books if b[0] == args.book_id), None)
        if not book:
            print(f"❌ Book ID {args.book_id} not found or has no cover")
            return 1
        
        book_id, book_path, title = book
        cover_path = os.path.join(library_path, book_path, 'cover.jpg')
        
        if not os.path.exists(cover_path):
            print(f"❌ Cover file not found: {cover_path}")
            return 1
        
        print(f"📖 Uploading cover for book {book_id}: {title}")
        success = upload_cover_to_s3(s3_client, S3_BUCKET, book_id, cover_path, args.dry_run, args.force)
        return 0 if success else 1
    
    elif args.all:
        # Upload all covers
        print("🚀 Starting bulk upload...")
        success_count = 0
        total_count = len(books)
        
        for i, (book_id, book_path, title) in enumerate(books, 1):
            cover_path = os.path.join(library_path, book_path, 'cover.jpg')
            
            if not os.path.exists(cover_path):
                print(f"  ⚠️  Cover file not found: {cover_path}")
                continue
            
            print(f"[{i}/{total_count}] Book {book_id}: {title}")
            
            if upload_cover_to_s3(s3_client, S3_BUCKET, book_id, cover_path, args.dry_run, args.force):
                success_count += 1
        
        print(f"\n📊 Upload complete: {success_count}/{total_count} covers uploaded successfully")
        return 0 if success_count == total_count else 1
    
    else:
        parser.print_help()
        return 1

if __name__ == '__main__':
    sys.exit(main())

