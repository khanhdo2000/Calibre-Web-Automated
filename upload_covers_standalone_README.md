# Standalone S3 Cover Upload Script

A standalone Python script to upload Calibre book covers to Amazon S3 without requiring the full Calibre-Web-Automated application.

## Features

- ✅ **Independent Operation** - Runs without CWA application
- ✅ **Auto-dependency Installation** - Automatically installs boto3 and Pillow if missing
- ✅ **Flexible Configuration** - Supports environment variables and command line arguments
- ✅ **S3 Integration** - Uploads covers to S3 with proper headers
- ✅ **Thumbnail Generation** - Automatically creates multiple thumbnail sizes (sm, md, lg)
- ✅ **Database Tracking** - Creates tracking records in CWA's app.db for each resolution
- ✅ **Duplicate Prevention** - Automatically skips already uploaded covers and thumbnails
- ✅ **Dry Run Support** - Test what would be uploaded without actually uploading
- ✅ **Selective Upload** - Upload all covers or specific book IDs
- ✅ **Force Re-upload** - Override duplicate check with --force flag
- ✅ **Error Handling** - Graceful error handling and progress reporting

## Usage

### Basic Usage

```bash
# Dry run to see what would be uploaded
./upload_covers_standalone.py --all --dry-run

# Upload all covers
./upload_covers_standalone.py --all

# Upload specific book
./upload_covers_standalone.py --book-id 59

# Use custom library path
./upload_covers_standalone.py --library-path /path/to/calibre/library --all
```

### Configuration Options

#### Environment Variables (Recommended)
```bash
export S3_BUCKET="your-bucket-name"
export S3_REGION="us-east-1"
export S3_ACCESS_KEY="your-access-key"
export S3_SECRET_KEY="your-secret-key"
```

#### Command Line Arguments
```bash
./upload_covers_standalone.py \
  --s3-bucket "your-bucket-name" \
  --s3-region "us-east-1" \
  --s3-access-key "your-access-key" \
  --s3-secret-key "your-secret-key" \
  --all
```

### Arguments

- `--library-path` - Path to Calibre library (default: ~/calibre-web)
- `--book-id` - Upload cover for specific book ID
- `--all` - Upload all covers
- `--dry-run` - Show what would be uploaded without actually uploading
- `--force` - Force re-upload even if already tracked in database
- `--s3-bucket` - S3 bucket name (required if not in env)
- `--s3-region` - S3 region (default: us-east-1)
- `--s3-access-key` - S3 access key (required if not in env)
- `--s3-secret-key` - S3 secret key (required if not in env)

## Requirements

- Python 3.6+
- Calibre library with metadata.db
- AWS S3 bucket and credentials
- boto3 (automatically installed if missing)
- Pillow (automatically installed if missing)

## What It Does

1. **Reads Calibre Library** - Connects to metadata.db to get book information
2. **Generates Thumbnails** - Creates multiple sizes (sm, md, lg) using PIL
3. **Uploads to S3** - Uploads cover files to S3 with proper headers
4. **Tracks Uploads** - Creates records in CWA's s3_cover_uploads table
5. **Reports Progress** - Shows upload progress and results

## S3 Structure

Covers are uploaded to: `s3://bucket-name/cw-cover/{book_id}/cover.jpg`

### Thumbnail Generation

The script automatically generates multiple thumbnail sizes for each cover:

- **Original**: `cw-cover/{book_id}/cover.jpg` (original size)
- **Small**: `cw-cover/{book_id}/cover_sm.jpg` (200px max dimension)
- **Medium**: `cw-cover/{book_id}/cover_md.jpg` (400px max dimension)  
- **Large**: `cw-cover/{book_id}/cover_lg.jpg` (800px max dimension)

Thumbnails are generated using high-quality Lanczos resampling and saved as optimized JPEG files.

## Database Tracking

The script creates tracking records in the CWA application database (`app.db`) in the `s3_cover_uploads` table to prevent duplicate uploads and enable fast lookups.

### Duplicate Prevention

- **Automatic Skip**: The script automatically skips books that are already tracked as uploaded
- **Force Override**: Use `--force` flag to re-upload even if already tracked
- **Database Lookup**: Checks the `s3_cover_uploads` table before uploading

### Database Locations

The script automatically finds the CWA database in these locations (in order):
1. `./config/app.db` (current directory)
2. `~/calibre-web-automated/config/app.db` (home directory)
3. `{script_directory}/config/app.db` (script directory)

## Security Note

**⚠️ Important**: This script requires S3 credentials. Never commit credentials to version control.
Always use environment variables or command-line arguments for credentials.

