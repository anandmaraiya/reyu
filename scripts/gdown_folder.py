#!/usr/bin/env python3
"""
Google Drive bulk download helper for NSE F&O intraday data.

Known public Google Drive folders with historical options data:
  1. TradingTuitions (NIFTY/BANKNIFTY 1-min options):
     https://drive.google.com/drive/folders/10pmUnHbT01rORkofkTzl1hB1eNtPZrOR
  2. debaonline4u/NSE-Data (Nifty 50 + Next 50 stocks, 1min-60min):
     https://drive.google.com/drive/folders/1zThEsziq0f4QpbdPyB3Z8F1pcKifmT3x

Requirements:
  pip install gdown

Usage:
  # Download entire folder (recursively)
  python scripts/gdown_folder.py --folder-id 10pmUnHbT01rORkofkTzl1hB1eNtPZrOR --output /data/nse_options

  # Download specific file
  python scripts/gdown_folder.py --file-id <FILE_ID> --output /data/nse_options

  # Ingest into DB after download
  curl -X POST "http://localhost:8000/api/data/intraday/ingest-folder?path=/data/nse_options&source=tradingtuitions"
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def download_folder(folder_id: str, output_dir: str, use_cookies: bool = False):
    """Download a Google Drive folder using gdown."""
    os.makedirs(output_dir, exist_ok=True)
    cmd = [
        sys.executable, "-m", "gdown",
        f"https://drive.google.com/drive/folders/{folder_id}",
        "--output", output_dir,
        "--remaining-ok",
    ]
    if use_cookies:
        cmd.append("--cookies-from-browser")
        cmd.append("chrome")

    print(f"Downloading folder {folder_id} to {output_dir}...")
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def download_file(file_id: str, output_dir: str):
    """Download a single Google Drive file."""
    os.makedirs(output_dir, exist_ok=True)
    cmd = [
        sys.executable, "-m", "gdown",
        f"https://drive.google.com/uc?id={file_id}",
        "--output", output_dir,
    ]
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def list_csv_files(output_dir: str) -> list:
    """List all CSV files in the download directory."""
    return sorted(Path(output_dir).rglob("*.csv"))


def main():
    parser = argparse.ArgumentParser(description="Download NSE options data from Google Drive")
    parser.add_argument("--folder-id", help="Google Drive folder ID")
    parser.add_argument("--file-id", help="Google Drive file ID")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--use-cookies", action="store_true", help="Use browser cookies for large downloads")
    args = parser.parse_args()

    if args.folder_id:
        success = download_folder(args.folder_id, args.output, args.use_cookies)
    elif args.file_id:
        success = download_file(args.file_id, args.output)
    else:
        print("Error: provide --folder-id or --file-id")
        sys.exit(1)

    if success:
        csvs = list_csv_files(args.output)
        print(f"\nDownload complete. Found {len(csvs)} CSV files.")
        if csvs:
            print("Sample files:")
            for f in csvs[:10]:
                print(f"  {f.relative_to(args.output)}")
            if len(csvs) > 10:
                print(f"  ... and {len(csvs) - 10} more")
    else:
        print("Download failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
