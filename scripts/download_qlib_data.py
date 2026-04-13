# -*- coding: utf-8 -*-
"""
Download Qlib CN stock data from official source
"""
import os
import sys
import subprocess

def download_qlib_data():
    """Download Qlib data using official script"""
    print("=" * 60)
    print("Download Qlib CN Stock Data")
    print("=" * 60)
    
    python_exe = sys.executable
    data_dir = os.path.expanduser("~/.qlib/qlib_data/cn_data")
    os.makedirs(data_dir, exist_ok=True)
    
    # Use qlib's official data download script
    # Reference: https://qlib.readthedocs.io/en/latest/component/data.html#prepared-data
    print("\nDownloading Qlib CN data (this may take a few minutes)...")
    
    # Method: Use python -m qlib.run.get_data
    # But this module may not exist in pyqlib 0.9.7
    # Alternative: Use the script from qlib repo
    
    # Try using pip to install qlib with data tools
    print("\n[Step 1] Installing qlib data tools...")
    result = subprocess.run(
        [python_exe, "-m", "pip", "install", "qlib[dev]"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("  qlib[dev] not available, trying alternative...")
    
    # Method: Direct download using Python
    print("\n[Step 2] Downloading data directly...")
    
    import urllib.request
    import tarfile
    
    # Official data URL from Qlib documentation
    url = "https://github.com/chenditc/invest_workshop/releases/download/2023-06-01/qlib_bin.tar.gz"
    archive_path = os.path.join(data_dir, "qlib_bin.tar.gz")
    
    print(f"  URL: {url}")
    print(f"  Target: {data_dir}")
    
    try:
        # Download with progress
        def report_progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(100, downloaded * 100 / total_size)
                sys.stdout.write(f"\r  Progress: {percent:.1f}% ({downloaded/1024/1024:.1f}MB / {total_size/1024/1024:.1f}MB)")
                sys.stdout.flush()
        
        urllib.request.urlretrieve(url, archive_path, reporthook=report_progress)
        print("\n  Download complete!")
        
        # Extract
        print("  Extracting...")
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(data_dir)
        print("  Extraction complete!")
        
        # Cleanup
        os.remove(archive_path)
        print("  Cleanup complete!")
        
        # Verify
        print("\n[Step 3] Verifying data...")
        import qlib
        qlib.init(provider_uri=data_dir)
        from qlib.data import D
        instruments = D.instruments('all')
        print(f"  Available stocks: {len(instruments)}")
        
        if len(instruments) > 100:
            print("\n  Data download successful!")
            return True
        else:
            print("\n  Warning: Only a few stocks found, data may be incomplete")
            return False
        
    except Exception as e:
        print(f"\n  Download failed: {e}")
        print("\n  Alternative methods:")
        print("  1. Download manually from:")
        print("     https://github.com/chenditc/invest_workshop/releases")
        print(f"  2. Extract to: {data_dir}")
        print("  3. Or use your existing TuShare data (see --convert option)")
        return False


if __name__ == '__main__':
    download_qlib_data()
