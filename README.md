# Synology Monitoring scripts

Hello Hello Gents of the Internet!
A few days ago I posted a screenshot from my iPhone of my Synology Infra monitoring dashboard. Some people demonstrated interest and asked me to provide instructions on how to achieve the same.
The idea here is to provide what you need to download and provide de configuration files for it. I won't go step by step since text is not the best form to explain complex procedures. That being said I believe anyone with a lit bit more than Basic knowledge will be able to follow along and deploy your version of this stack.

!!! DISCLAIMER !!!
This is a pre alpha release, expect bugs, dirty code and be ready to spot lots of improvements that will come down the road when I turn everything you see here in a library.

Tools -

Telegraf -  docker pull telegraf
InfluxDB - docker pull influxdb
Grafana -  docker pull grafana/grafana
Python3 + Scripts - docker pull centos

## Setup
1. **InfluxDB 2.0+**: Ensure you have an InfluxDB instance running with a Bucket and Token created.
2. **Python Environment**: Install dependencies using the provided requirements file:
   ```bash
   pip install -r requirements.txt
   ```
3. **GeoIP**: The scripts require the `GeoLite2-City.mmdb` database. You can download it manually or use the provided utility script (requires a MaxMind License Key):
   ```bash
   # Option 1: Using environment variable
   export MAXMIND_LICENSE_KEY=your_license_key
   python src/update_geoip.py

   # Option 2: Passing as an argument
   python src/update_geoip.py your_license_key
   ```

## Monitoring Scripts

### Internet Speed (Monitor-Internet.py)
Uses `speedtest-cli` to track bandwidth. Update `config_internet.ini` with your InfluxDB details.

### Router Status (Monitor-Router.py)
This script now executes commands directly on your Synology Router via SSH using `synowebapi`.
- **Requirement**: SSH must be enabled on the router.
- **Auth**: Uses an SSH Key for passwordless execution.
- **Config**: Update `config_router.ini` with your SSH host and InfluxDB token.

## Running Tests
This project uses `pytest` for validation. Run:
```bash
pytest test_monitoring.py
```

OUTLAND.Remote.Network.VPNPlus
OUTLAND.Remote.System.CPU
OUTLAND.Remote.System.Memory
OUTLAND.Remote.Network.ConnectedDevices
OUTLAND.Remote.Network.DHCP
OUTLAND.Remote.Network.Wifi.Channels                  - Collected every 1 hour.
OUTLAND.Remote.Network.FW.Summary.LastDay             - Collected every 1 hour.
OUTLAND.Remote.Network.FW.Summary.Bandwidth.Day       - Collected every 1 hour.
OUTLAND.Remote.Network.FW.Summary.Bandwidth.Week      - Collected every 1 day(at 3AM+-)
OUTLAND.Remote.Network.FW.Summary.Bandwidth.Month     - Collected every 1 day(at 3AM+-)
OUTLAND.Remote.Network.FW.Summary.Bandwidth.Year.     - Collected every 1 day(at 3AM+-)
OUTLAND.Remote.Network.FW.Summary.Domain.day          - Collected every day(at 5AM+-)
OUTLAND.Remote.Network.FW.Summary.Url.Live
OUTLAND.Remote.Network.FW.WebTraffic.Live
OUTLAND.Remote.System.Logs.Connection
