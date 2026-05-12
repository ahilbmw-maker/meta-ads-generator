"""
Drive uploader module - uploads localized videos to Google Drive
SKU folders are created on-the-fly and cached in /data/drive_folders.json
"""
import os
import json
import tempfile
import requests
from typing import Optional, Dict
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account


SCOPES = ['https://www.googleapis.com/auth/drive']
DRIVE_FOLDERS_CACHE = '/data/drive_folders.json'
ROOT_FOLDER_ID = os.environ.get('MAAARKET_ADS_ROOT_FOLDER_ID', '')


def _get_drive_service():
    """Authenticate with Service Account from env var."""
    sa_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var not set")
    sa_info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


def _load_folder_cache() -> Dict[str, dict]:
    """Load SKU → {folder_id, share_link} mapping from disk."""
    if not os.path.exists(DRIVE_FOLDERS_CACHE):
        return {}
    try:
        with open(DRIVE_FOLDERS_CACHE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_folder_cache(cache: Dict[str, dict]):
    os.makedirs(os.path.dirname(DRIVE_FOLDERS_CACHE), exist_ok=True)
    with open(DRIVE_FOLDERS_CACHE, 'w') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _make_link_shareable(service, file_id: str) -> str:
    """Set permission 'Anyone with link can view' and return shareable link."""
    # Set permission
    service.permissions().create(
        fileId=file_id,
        body={'type': 'anyone', 'role': 'reader'},
        fields='id'
    ).execute()
    # Get webViewLink
    file_meta = service.files().get(fileId=file_id, fields='webViewLink').execute()
    return file_meta.get('webViewLink', '')


def get_or_create_sku_folder(sku_name: str) -> dict:
    """
    Get folder_id and share_link for SKU. Creates folder if doesn't exist.
    Returns: {"folder_id": "...", "share_link": "https://drive.google.com/..."}
    """
    cache = _load_folder_cache()
    if sku_name in cache and cache[sku_name].get('folder_id'):
        return cache[sku_name]

    if not ROOT_FOLDER_ID:
        raise RuntimeError("MAAARKET_ADS_ROOT_FOLDER_ID env var not set")

    service = _get_drive_service()

    # Create folder inside root
    folder_metadata = {
        'name': sku_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [ROOT_FOLDER_ID]
    }
    folder = service.files().create(
        body=folder_metadata,
        fields='id'
    ).execute()
    folder_id = folder.get('id')

    # Make folder shareable - anyone with link
    share_link = _make_link_shareable(service, folder_id)

    cache[sku_name] = {
        'folder_id': folder_id,
        'share_link': share_link
    }
    _save_folder_cache(cache)
    return cache[sku_name]


def upload_video_to_drive(video_url: str, sku_name: str, country_code: str, video_version: int) -> dict:
    """
    Download video from URL and upload to SKU folder in Drive.
    Returns: {"file_id", "filename", "file_link", "folder_link"}
    """
    folder_info = get_or_create_sku_folder(sku_name)
    folder_id = folder_info['folder_id']

    filename = f"video_{country_code.lower()}_v{video_version}.mp4"

    # Download video to temp file
    r = requests.get(video_url, stream=True, timeout=120)
    r.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
            if chunk:
                tmp.write(chunk)
        tmp_path = tmp.name

    try:
        service = _get_drive_service()
        # Check if file with same name already exists in folder - replace
        existing = service.files().list(
            q=f"name = '{filename}' and '{folder_id}' in parents and trashed = false",
            fields='files(id, name)'
        ).execute()

        media = MediaFileUpload(tmp_path, mimetype='video/mp4', resumable=True)

        if existing.get('files'):
            # Update existing file
            file_id = existing['files'][0]['id']
            file = service.files().update(
                fileId=file_id,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()
        else:
            # Create new file
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()

        return {
            'file_id': file.get('id'),
            'filename': file.get('name'),
            'file_link': file.get('webViewLink'),
            'folder_link': folder_info['share_link']
        }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def list_sku_folders() -> Dict[str, dict]:
    """Return all known SKU folders for UI display."""
    return _load_folder_cache()
