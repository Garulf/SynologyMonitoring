import time as alternativeTime
from datetime import datetime, time
import logging
import sys
import os

# Adjust path to find the monitor_router module if running from src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from monitor_router.monitor import SynologyRouterMonitor
from monitor_router.utils import is_time_between

def main_block(monitor):
    monitor.coreSystemStatus()
    monitor.networkDHCPDevices()

    # Hourly tasks
    current_time = datetime.now().time()
    if is_time_between(time(datetime.now().hour, 0), time(datetime.now().hour, 45), current_time):
        monitor.networkWifiChannel()
        monitor.networkFirewallConnectionsLastDay()

    monitor.networkConnectedDevices()
    monitor.vpnPlusOnlineSessions()

    # Periodic Bandwidth Checks
    if is_time_between(time(datetime.now().hour, 0), time(datetime.now().hour, 30), current_time):
        monitor.networkFirewallBandwidthCheck('day')
    
    # Daily Maintenance Tasks (around 3 AM and 5 AM)
    if is_time_between(time(3, 1), time(3, 30), current_time):
        monitor.networkFirewallBandwidthCheck('week')
    if is_time_between(time(3, 31), time(4, 0), current_time):
        monitor.networkFirewallBandwidthCheck('month')
    if is_time_between(time(4, 1), time(4, 30), current_time):
        monitor.networkFirewallBandwidthCheck('year')
    
    if is_time_between(time(5, 0), time(5, 59), current_time):
        monitor.networkFirewallDomainLastDay()

    monitor.networkFirewallUrlLive()
    monitor.networkFirewallWebTraffic()
    monitor.getConnectionLogsOutland()

def main_runner(monitor):
    start_time = alternativeTime.time()
    main_block(monitor)
    elapsed = alternativeTime.time() - start_time
    sleep_time = max(0, 30.0 - (elapsed % 30.0))
    alternativeTime.sleep(sleep_time)

if __name__ == "__main__":
    monitor = SynologyRouterMonitor(config_path='config_router.ini')
    while True:
        try:
            main_runner(monitor)
        except Exception as e:
            logging.exception(f"Critical failure in main loop: {e}")
            alternativeTime.sleep(10) # Cooling period before retry