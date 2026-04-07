import os
import tarfile
import urllib.request
import shutil
import sys

def download_geoip():
    """
    Downloads and extracts the GeoLite2-City database from MaxMind.
    Requires a MAXMIND_LICENSE_KEY.
    """
    # Priority: Command line arg -> Environment variable
    license_key = sys.argv[1] if len(sys.argv) > 1 else os.getenv('MAXMIND_LICENSE_KEY')
    
    if not license_key:
        print("ERROR: MaxMind License Key not provided.")
        print("Usage: python src/update_geoip.py <LICENSE_KEY>")
        print("Or set the MAXMIND_LICENSE_KEY environment variable.")
        sys.exit(1)

    url = f"https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&suffix=tar.gz&license_key={license_key}"
    target_tar = "GeoLite2-City.tar.gz"
    extract_dir = "geoip_temp"

    # Some servers block the default Python User-Agent
    opener = urllib.request.build_opener()
    opener.addheaders = [('User-agent', 'Mozilla/5.0')]
    urllib.request.install_opener(opener)

    print("Downloading GeoLite2-City database...")
    try:
        urllib.request.urlretrieve(url, target_tar)
        
        print("Extracting database...")
        with tarfile.open(target_tar, "r:gz") as tar:
            tar.extractall(path=extract_dir)
            
        # Find and move the .mmdb file to the project root
        found = False
        for root, _, files in os.walk(extract_dir):
            for file in files:
                if file.endswith(".mmdb"):
                    dest = os.path.join(os.getcwd(), "GeoLite2-City.mmdb")
                    shutil.move(os.path.join(root, file), dest)
                    found = True
                    break
            if found: break
        
        print("Successfully updated GeoLite2-City.mmdb" if found else "ERROR: .mmdb file not found in archive.")
        
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if os.path.exists(target_tar): os.remove(target_tar)
        if os.path.exists(extract_dir): shutil.rmtree(extract_dir)

if __name__ == "__main__":
    download_geoip()