import json
import configparser
import os
import paramiko
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import timezone, time, datetime, timedelta
import time as alternativeTime
import geoip2.database
import socket
import Geohash
import logging
import sys

LOG_FILENAME = 'queryOutlandApis.log'
logging.basicConfig(filename=LOG_FILENAME, level=logging.ERROR)

class ConfigManager:
    def __init__(self, config_path):
        config_file = os.path.join(os.getcwd(), config_path)
        if not os.path.isfile(config_file):
            print(f'ERROR: Unable To Load Config File: {config_file}')
            sys.exit(1)
        
        self.config = configparser.ConfigParser()
        self.config.read(config_file)

        # InfluxDB
        self.influx_url = self.config['INFLUXDB']['Url']
        self.influx_token = self.config['INFLUXDB']['Token']
        self.influx_org = self.config['INFLUXDB']['Org']
        self.influx_bucket = self.config['INFLUXDB'].get('Bucket', fallback='telegraf')
        self.influx_verify_ssl = self.config['INFLUXDB'].getboolean('Verify_SSL', fallback=True)

        # SSH
        self.ssh_host = self.config['SSH']['Host']
        self.ssh_user = self.config['SSH']['User']
        self.ssh_key = self.config['SSH']['KeyPath']

class SynologyRouterMonitor:
    def __init__(self, config_path='config_router.ini'):
        self.cfg = ConfigManager(config_path)
        self.ssh = None
        self.gi = None
        self._setup_influx()
        self._setup_geoip()

    def _setup_influx(self):
        self.influx_client = InfluxDBClient(
            url=self.cfg.influx_url,
            token=self.cfg.influx_token,
            org=self.cfg.influx_org,
            verify_ssl=self.cfg.influx_verify_ssl
        )
        self.write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)

    def _setup_geoip(self):
        try:
            self.gi = geoip2.database.Reader('GeoLite2-City.mmdb')
        except Exception as e:
            print(f"Warning: Could not load GeoIP database: {e}")

    def _connect_ssh(self):
        """Establishes or verifies the SSH connection."""
        if self.ssh is not None and self.ssh.get_transport() and self.ssh.get_transport().is_active():
            return

        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.ssh.connect(self.cfg.ssh_host, username=self.cfg.ssh_user, key_filename=self.cfg.ssh_key)
        except Exception as e:
            logging.error(f"SSH Connection Failed: {e}")
            self.ssh = None

    def exec_syno_api(self, api, method, version, **kwargs):
        self._connect_ssh()
        if not self.ssh: return {"success": False}

        syno_args = [f"api={api}", f"method={method}", f"version={version}"]
        for k, v in kwargs.items():
            syno_args.append(f"{k}='{v}'")
        
        remote_cmd = f"synowebapi --exec {' '.join(syno_args)}"
        _, stdout, _ = self.ssh.exec_command(remote_cmd)
        return json.loads(stdout.read().decode('utf-8'))

    def influx_sender(self, influx_payload, bucket=None):
        target_bucket = bucket or self.cfg.influx_bucket
        self.write_api.write(bucket=target_bucket, org=self.cfg.influx_org, record=influx_payload)


# Get ISO time
def now_iso():
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    return now_iso


def errorLvl(argument):
    switcher = {
        "info": 1,
        "warn": 2,
        "error": 3,
    }
    return switcher.get(argument)


def findDeviceName(jsonDic, deviceMac):
    for item in jsonDic:
        if item['mac'] == deviceMac:
            return item['hostname']


def is_time_between(begin_time, end_time, check_time=None):
    # If check time is not given, default to current UTC time
    check_time = check_time or datetime.utcnow().time()
    if begin_time < end_time:
        return check_time >= begin_time and check_time <= end_time
    else: # crosses midnight
        return check_time >= begin_time or check_time <= end_time


def is_time(eventTime):
    nowDateTime = datetime.now() - timedelta(seconds=30)
    return eventTime >= nowDateTime

def listKnowDevices(self):
    jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic.Device', 'get', '1')
    return jsonDic.get('data', [])

def vpnPlusHistoricSessions(self):
    jsonDic = self.exec_syno_api('SYNO.VPNPlus.Connectivity', 'list_uid_aggr', '1')
    result = jsonDic['data']['uid_aggr_list']
    return result

def vpnPlusOnlineSessions(self):
    jsonDic = self.exec_syno_api('SYNO.VPNPlus.Connectivity', 'list', '1', status='online')
    result = jsonDic['data']['cnt_list']

    influxPayloadVpnPlusActiveSessions= []
    for item in result:
        if item['ip_from'] != "0.0.0.0" and self.gi:
            INFO = self.gi.city(item['ip_from'])           
            HASH = Geohash.encode(INFO.location.latitude, INFO.location.longitude)
            country_code = INFO.country.iso_code
            if INFO.city.name != "" and INFO.city.name is not None:
                location_name = INFO.city.name
            else:
                location_name = country_code   
        else:
            HASH = "Blocked"
            location_name = "Blocked"
            country_code = "Blocked"            
        influxPayloadVpnPlusActiveSessions.append(
            {
                    "measurement": "OUTLAND.Remote.Network.VPNPlus",
                    "tags": {           
                                        "username":item['username'],
                                        "geohash": HASH,
                                        "country_code":country_code, 
                                        "location_name":location_name,                                                                                                    
                                        "externalIP":item['ip_from'],                                    
                                        "internalIP":item['signature']                                    
                            },
                            "time": now_iso(),
                            "fields": { 
                                        "externalIP":item['ip_from'],                                    
                                        "internalIP":item['signature'],
                                        "abnormal":item['abnormal'],                                                                       
                                        "download":item['download'],                                                                       
                                        "upload":item['upload'],
                                        "count": 1,
                                        "time_duration":item['time_duration'],
                                        "time_start":datetime.fromtimestamp(float(item['time_start'])).strftime('%Y-%m-%d %H:%M:%S')
                                    }
                            }                   
        )
    self.influx_sender(influxPayloadVpnPlusActiveSessions,'telegraf')
    return influxPayloadVpnPlusActiveSessions

def vpnPlusOpenSites(self):
    jsonDic = self.exec_syno_api('SYNO.VPNPlus.WebPortal.Sites', 'list', '1')
    result = jsonDic['data']['sites']
    return result

def coreSystemStatus(self):
    jsonDic = self.exec_syno_api('SYNO.Core.System.Utilization', 'get', '1')
    result = jsonDic['data']
    
    influxPayloadOutlandStatus= []
    influxPayloadOutlandStatus.append(
        {
                "measurement": "OUTLAND.Remote.System.CPU",
                "tags": {           
                        },
                        "time": now_iso(),
                        "fields": {
                                    "user_load":result['cpu']['user_load'],
                                    "system_load":result['cpu']['system_load'],                                                                                           
                                    "other_load":result['cpu']['other_load'],                                                                                           
                                    "1min_load":result['cpu']['1min_load'],                                                                
                                    "5min_load":result['cpu']['5min_load'],  
                                    "15min_load":result['cpu']['15min_load']
                                }
                        }                   
    )
    self.influx_sender(influxPayloadOutlandStatus,'telegraf')

    influxPayloadOutlandStatus= []
    influxPayloadOutlandStatus.append(
        {
                "measurement": "OUTLAND.Remote.System.Memory",
                "tags": {           
                        },
                        "time": now_iso(),
                        "fields": {
                                    "memory_size":result['memory']['memory_size'],
                                    "total_swap":result['memory']['buffer'],
                                    "total_real":result['memory']['total_real'],                                                                                           
                                    "real_usage":result['memory']['real_usage'],                                                                                           
                                    "avail_real":result['memory']['avail_real'],                                                                
                                    "avail_swap":result['memory']['avail_swap'],  
                                    "buffer":result['memory']['buffer'],
                                    "cached":result['memory']['cached']
                                }
                        }                   
    )
    self.influx_sender(influxPayloadOutlandStatus,'telegraf')
    return influxPayloadOutlandStatus

def networkConnectedDevices(self):
    jsonDic = self.exec_syno_api('SYNO.Core.Network.NSM.Device', 'get', '1')
    result = jsonDic['data']['devices']

    influxPayloadConnectedDevices= []
    for item in result:    
        if True == item['is_online']:
            if True == item['is_wireless']:
                influxPayloadConnectedDevices.append(
                            {
                                "measurement": "OUTLAND.Remote.Network.ConnectedDevices",
                                "tags": {
                                    "band":item['band'],
                                    "connection":item['connection'],                                
                                    "hostname": item['hostname'],                                
                                    "is_baned":item['is_baned'],
                                    "is_guest":item['is_guest'],
                                    "is_high_qos":item['is_high_qos'],
                                    "is_low_qos":item['is_low_qos'],
                                    "is_qos":item['is_qos'],
                                    "is_wireless":item['is_wireless'],                                                                
                                    "mac":item['mac']                                                        
                                    #"mesh_node_id":item['mesh_node_id'],                                
                                },
                                "time": now_iso(),
                                "fields": {                                    
                                        "max_rate":item['max_rate'], 
                                        "current_rate":item['current_rate'],
                                        "transferRXRate":item['transferRXRate'],     
                                        "transferTXRate":item['transferTXRate'],
                                        "signalstrength":item['signalstrength'],
                                        "rate_quality":item['rate_quality'],
                                        "internalIP":item['ip_addr']                                                            
                                }
                            }
                )
            else:
                influxPayloadConnectedDevices.append(
                            {
                                "measurement": "OUTLAND.Remote.Network.ConnectedDevices",
                                "tags": {
                                    "connection":item['connection'],
                                    "hostname":item['hostname'],                                
                                    "is_baned":item['is_baned'],
                                    "is_high_qos":item['is_high_qos'],
                                    "is_low_qos":item['is_low_qos'],
                                    "is_qos":item['is_qos'],                                
                                    "is_wireless":item['is_wireless'],
                                    "mac":item['mac']                               
                                },
                                "time": now_iso(),
                                "fields": {       
                                    "internalIP":item['ip_addr']                          
                                }
                            }
                )
            self.influx_sender(influxPayloadConnectedDevices,'telegraf')
    return influxPayloadConnectedDevices

def networkDHCPDevices(self):
    jsonDic = self.exec_syno_api('SYNO.Core.Network.DHCPServer.ClientList', 'list', '2', ifname='lbr0')
    result = jsonDic['data']['clientList']['ipv4']

    influxPayloadConnectedDevicesDHCP= []
    for item in result:   
        influxPayloadConnectedDevicesDHCP.append(
            {
                    "measurement": "OUTLAND.Remote.Network.DHCP",
                    "tags": {           
                                        "hostname":item['hostname'],
                                        "mac":item['clid']
                            },
                            "time": now_iso(),
                            "fields": {                                    
                                        "expire":item['expire'],
                                        "internalIP":item['ip']   
                                    }
                            }                   
        )
    self.influx_sender(influxPayloadConnectedDevicesDHCP,'telegraf')
    return influxPayloadConnectedDevicesDHCP

def networkWifiChannel(self):
    jsonDic = self.exec_syno_api('SYNO.Core.Network.Wifi.Hotspot', 'list', '2')
    result = jsonDic['data']

    influxPayloadWifiChannels= []
    for item in result:   
        influxPayloadWifiChannels.append(
            {
                    "measurement": "OUTLAND.Remote.Network.Wifi.Channels",
                    "tags": {           
                                        "netif":item['netif']                                    
                            },
                            "time": now_iso(),
                            "fields": {                                    
                                        "current_channel":item['current_channel'],                                    
                                        "status":item['status']
                                    }
                            }                   
        )
    self.influx_sender(influxPayloadWifiChannels,'telegraf')
    return influxPayloadWifiChannels

def networkFirewallConnectionsLastDay(self):
    jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic.Domain', 'get_devices', '1', interval='day')
    result = jsonDic['data']

    influxPayloadNetworkFirewallConnectionsLastDay= []
    totalConnections = sum(d['count'] for d in result if d) 
    for item in result:           
        userTotal = (int((item['count']) * 100) / totalConnections)
        userTotal = round(userTotal,1)
        influxPayloadNetworkFirewallConnectionsLastDay.append(
            {
                    "measurement": "OUTLAND.Remote.Network.FW.Summary.LastDay",
                    "tags": {           
                                        "hostname":item['hostname']                                    
                            },
                            "time": now_iso(),
                            "fields": { 
                                        "count":item['count'],
                                        "percentage":userTotal
                                    }
                            }                   
        )
    self.influx_sender(influxPayloadNetworkFirewallConnectionsLastDay,'telegraf')
    return influxPayloadNetworkFirewallConnectionsLastDay

def networkFirewallBandwidthCheck(self, interval):
    jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic', 'get', '1', interval=interval, mode='net_l7')
    result = jsonDic['data']

    #Get List of Know Devices
    knowDevices = self.listKnowDevices()
    influxPayloadNetworkFirewallBandwidthLastDay= []
    for item in result:           
        deviceName = findDeviceName(knowDevices,item['deviceID'])
        influxPayloadNetworkFirewallBandwidthLastDay.append(
            {
                    "measurement": "OUTLAND.Remote.Network.FW.Summary.Bandwidth." + interval,
                    "tags": {           
                                        "hostname":deviceName                                  
                            },
                            "time": now_iso(),
                            "fields": { 
                                        "download":item['download'],
                                        "download_packets":item['download_packets'],
                                        "upload":item['upload'],
                                        "upload_packets":item['upload_packets'],
                                    }
                            }                   
        )
        self.influx_sender(influxPayloadNetworkFirewallBandwidthLastDay,'telegraf')
    return influxPayloadNetworkFirewallBandwidthLastDay

def networkFirewallDomainLastDay(self):
    jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic.Domain', 'get', '1', interval='day')
    result = jsonDic['data']

    payloadDomainLastDay= []
    for item in result:  
        if item['count']  > 5:      
            payloadDomainLastDay.append(
                {
                        "measurement": "OUTLAND.Remote.Network.FW.Summary.Domain.day" ,
                        "tags": {           
                                            "domainName":item['domainName']                                  
                                },
                                "time": now_iso(),
                                "fields": { 
                                            "count":item['count'],
                                            "domainId":item['domainId']
                                        }
                                }                   
            )
            self.influx_sender(payloadDomainLastDay,'telegraf')
    return payloadDomainLastDay
    
def networkFirewallUrlLive(self):
    jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic.Domain', 'get', '1', interval='live')
    result = jsonDic['data']

    #Get List of Know Devices
    knowDevices = self.listKnowDevices()

    payloadUrlLive = []
    for item in result:  
        try:
            ipData = item['domain'].split(':')[0]
            ipData = socket.gethostbyname(ipData)
        except:
            ipData = '0.0.0.0'
        if ipData != '0.0.0.0' and self.gi:
            try:
                INFO = self.gi.city(ipData)
                HASH = Geohash.encode(INFO.location.latitude, INFO.location.longitude)
                country_code = INFO.country.iso_code
                if INFO.city.name != "" and INFO.city.name is not None:
                    location_name = INFO.city.name
                else:
                    location_name = country_code
            except:
                HASH = "Unknow"
                location_name = "Unknow"
                country_code = "Unknow"
        else:
            HASH = "Blocked"
            location_name = "Blocked"
            country_code = "Blocked"
        #print(str(location_name)  + ' - ' +  str(country_code))
        parsedDateTime = datetime.fromtimestamp(float(item['timestamp']))
        if is_time(parsedDateTime) == True:
            deviceName = findDeviceName(knowDevices,item['mac'])
            payloadUrlLive.append(
                {
                        "measurement": "OUTLAND.Remote.Network.FW.Summary.Url.Live",
                        "tags": {           
                                            "deviceName":deviceName,
                                            "country_code":country_code, 
                                            "location_name":location_name,
                                            "geohash": HASH,
                                            "protocol":item['protocol']                            
                                },
                                "time": now_iso(),
                                "fields": { 
                                            "detail":item['detail'],
                                            "domainName":item['domain'],
                                            "count": 1,
                                            "timestamp":parsedDateTime.strftime('%Y-%m-%d %H:%M:%S')
                                        }
                                }                   
            )
            self.influx_sender(payloadUrlLive,'telegraf')
    return payloadUrlLive

def networkFirewallWebTraffic(self):
    jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic', 'get', '1', mode='net', interval='live')
    result = jsonDic['data']

    #Get List of Know Devices
    knowDevices = self.listKnowDevices()

    payloadWebTrafficLive = []
    for item in result:  
        deviceName = findDeviceName(knowDevices,item['deviceID'])
        payloadWebTrafficLive.append(
            {
                    "measurement": "OUTLAND.Remote.Network.FW.WebTraffic.Live" ,
                    "tags": {           
                                        "deviceName":deviceName                                     
                            },
                            "time": now_iso(),
                            "fields": { 
                                        "download":item['download'],
                                        "upload":item['upload']                                        
                                    }
                            }                   
        )
        self.influx_sender(payloadWebTrafficLive,'telegraf')
    return payloadWebTrafficLive

def getConnectionLogsOutland(self):
    jsonDic = self.exec_syno_api('SYNO.Core.SyslogClient.Log', 'list', '1', limit='100', target='LOCAL')
    result = jsonDic['data']['items']

    payloadConnectionLogsOutland = []    
    for item in result:                 
        parsedDateTime = datetime.strptime(item['time'],'%Y/%m/%d %H:%M:%S')
        if is_time(parsedDateTime) == True:
            logLevelInt = errorLvl(item['level'])   
            if 'failed' in item['descr']:
                logLevelInt = 3
            else:
                if 'logged' in item['descr']:
                    logLevelInt = 6
            payloadConnectionLogsOutland.append(
                {
                        "measurement": "OUTLAND.Remote.System.Logs.Connection" ,
                        "tags": {                                                   
                                            "user":item['who'],                                        
                                            "logtype":item['logtype'],
                                            "level":item['level'],                                                                                
                                            "timestamp":item['time'],      
                                            'orginalLogType':item['orginalLogType'],                                                                      
                                            'loglevelInt':logLevelInt
                                },
                                "time": now_iso(),
                                "fields": {      
                                            "descr":item['descr']                                        
                                        }
                                }                   
            )        
            self.influx_sender(payloadConnectionLogsOutland,'telegraf')
    return payloadConnectionLogsOutland

# Attach methods to class
SynologyRouterMonitor.listKnowDevices = listKnowDevices
SynologyRouterMonitor.vpnPlusHistoricSessions = vpnPlusHistoricSessions
SynologyRouterMonitor.vpnPlusOnlineSessions = vpnPlusOnlineSessions
SynologyRouterMonitor.vpnPlusOpenSites = vpnPlusOpenSites
SynologyRouterMonitor.coreSystemStatus = coreSystemStatus
SynologyRouterMonitor.networkConnectedDevices = networkConnectedDevices
SynologyRouterMonitor.networkDHCPDevices = networkDHCPDevices
SynologyRouterMonitor.networkWifiChannel = networkWifiChannel
SynologyRouterMonitor.networkFirewallConnectionsLastDay = networkFirewallConnectionsLastDay
SynologyRouterMonitor.networkFirewallBandwidthCheck = networkFirewallBandwidthCheck
SynologyRouterMonitor.networkFirewallDomainLastDay = networkFirewallDomainLastDay
SynologyRouterMonitor.networkFirewallUrlLive = networkFirewallUrlLive
SynologyRouterMonitor.networkFirewallWebTraffic = networkFirewallWebTraffic
SynologyRouterMonitor.getConnectionLogsOutland = getConnectionLogsOutland

def mainBlock(monitor):
    #Main Calls

    #System Status CPU/Memory
    monitor.coreSystemStatus()
    ###################################################################################

    #Network DHCP Clients
    monitor.networkDHCPDevices()
    ###################################################################################

    #Wifi Channels
    runWindowHourly = is_time_between(time(int(datetime.now().hour),00,00), time(int(datetime.now().hour),00,45),datetime.now().time())
    if runWindowHourly == True:
        monitor.networkWifiChannel()
    ###################################################################################

    #Connected Devices
    monitor.networkConnectedDevices()
    ###################################################################################

    #VPN Plus Active Sessions
    monitor.vpnPlusOnlineSessions()
    ###################################################################################

    #Firewall Get Connections Last Day 
    runWindowHourly = is_time_between(time(int(datetime.now().hour),00,00), time(int(datetime.now().hour),00,45),datetime.now().time())
    if runWindowHourly == True:
        monitor.networkFirewallConnectionsLastDay()
    ###################################################################################

    #Firewall Get Bandwidth Last Day
    runWindowDay = is_time_between(time(int(datetime.now().hour),00,00), time(int(datetime.now().hour),00,30),datetime.now().time())
    if runWindowDay == True:
        monitor.networkFirewallBandwidthCheck('day')
    runWindowDay = is_time_between(time(3,1,00), time(3,1,30),datetime.now().time())
    if runWindowDay == True:
        monitor.networkFirewallBandwidthCheck('week')
    runWindowDay = is_time_between(time(3,2,00), time(3,2,30),datetime.now().time())
    if runWindowDay == True:
        monitor.networkFirewallBandwidthCheck('month')
    runWindowDay = is_time_between(time(3,3,00), time(3,3,30),datetime.now().time())
    if runWindowDay == True:
        monitor.networkFirewallBandwidthCheck('year')
     
    ###################################################################################

    #Firewall Get Domain Last Day
    runWindowDay = is_time_between(time(5,00,30), time(5,00,59),datetime.now().time())
    if runWindowDay == True:
        monitor.networkFirewallDomainLastDay()
    ###################################################################################

    #Firewall Get URL Live
    monitor.networkFirewallUrlLive()
    ###################################################################################

    #Firewall Get Live Web Traffic
    monitor.networkFirewallWebTraffic()
    ###################################################################################

    #Connection Logs
    monitor.getConnectionLogsOutland()
    ###################################################################################


def mainRunner(monitor):
    starttime=alternativeTime.time()
    mainBlock(monitor)
    alternativeTime.sleep(30.0 - ((alternativeTime.time() - starttime) % 30.0))

if __name__ == "__main__":
    monitor = SynologyRouterMonitor()
    monitor.networkFirewallUrlLive()
    while True:
        try:
            mainRunner(monitor)
        except Exception as e:
            print('Failed! - ' +  str(e))
            logging.exception('Failed on main while!')
            raise