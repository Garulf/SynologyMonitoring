import json
import paramiko
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime
import geoip2.database
import socket
import Geohash
import logging

from .config import ConfigManager
from .utils import now_iso, errorLvl, findDeviceName, is_time

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
            logging.warning(f"Could not load GeoIP database: {e}")

    def _connect_ssh(self):
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

    def listKnowDevices(self):
        jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic.Device', 'get', '1')
        return jsonDic.get('data', [])

    def vpnPlusOnlineSessions(self):
        jsonDic = self.exec_syno_api('SYNO.VPNPlus.Connectivity', 'list', '1', status='online')
        result = jsonDic.get('data', {}).get('cnt_list', [])

        influxPayload = []
        for item in result:
            if item['ip_from'] != "0.0.0.0" and self.gi:
                INFO = self.gi.city(item['ip_from'])           
                HASH = Geohash.encode(INFO.location.latitude, INFO.location.longitude)
                location_name = INFO.city.name or INFO.country.iso_code or "Unknown"
                country_code = INFO.country.iso_code or "Unknown"
            else:
                HASH = "Blocked"
                location_name = "Blocked"
                country_code = "Blocked"            
            influxPayload.append({
                "measurement": "OUTLAND.Remote.Network.VPNPlus",
                "tags": { "username":item['username'], "geohash": HASH, "country_code":country_code, "location_name":location_name, "externalIP":item['ip_from'], "internalIP":item['signature'] },
                "time": now_iso(),
                "fields": { "externalIP":item['ip_from'], "internalIP":item['signature'], "abnormal":item['abnormal'], "download":item['download'], "upload":item['upload'], "count": 1, "time_duration":item['time_duration'], "time_start":datetime.fromtimestamp(float(item['time_start'])).strftime('%Y-%m-%d %H:%M:%S') }
            })
        self.influx_sender(influxPayload, 'telegraf')

    def coreSystemStatus(self):
        jsonDic = self.exec_syno_api('SYNO.Core.System.Utilization', 'get', '1')
        result = jsonDic.get('data', {})
        
        cpu_payload = [{
            "measurement": "OUTLAND.Remote.System.CPU",
            "time": now_iso(),
            "fields": { "user_load":result['cpu']['user_load'], "system_load":result['cpu']['system_load'], "other_load":result['cpu']['other_load'], "1min_load":result['cpu']['1min_load'], "5min_load":result['cpu']['5min_load'], "15min_load":result['cpu']['15min_load'] }
        }]
        self.influx_sender(cpu_payload, 'telegraf')

        mem_payload = [{
            "measurement": "OUTLAND.Remote.System.Memory",
            "time": now_iso(),
            "fields": { "memory_size":result['memory']['memory_size'], "total_swap":result['memory']['buffer'], "total_real":result['memory']['total_real'], "real_usage":result['memory']['real_usage'], "avail_real":result['memory']['avail_real'], "avail_swap":result['memory']['avail_swap'], "buffer":result['memory']['buffer'], "cached":result['memory']['cached'] }
        }]
        self.influx_sender(mem_payload, 'telegraf')

    def networkConnectedDevices(self):
        jsonDic = self.exec_syno_api('SYNO.Core.Network.NSM.Device', 'get', '1')
        result = jsonDic.get('data', {}).get('devices', [])

        influxPayload = []
        for item in result:    
            if item.get('is_online'):
                tags = { "connection":item['connection'], "hostname": item['hostname'], "is_baned":item['is_baned'], "is_high_qos":item['is_high_qos'], "is_low_qos":item['is_low_qos'], "is_qos":item['is_qos'], "is_wireless":item['is_wireless'], "mac":item['mac'] }
                fields = { "internalIP":item['ip_addr'] }
                
                if item.get('is_wireless'):
                    tags.update({"band":item['band']})
                    fields.update({ "max_rate":item['max_rate'], "current_rate":item['current_rate'], "transferRXRate":item['transferRXRate'], "transferTXRate":item['transferTXRate'], "signalstrength":item['signalstrength'], "rate_quality":item['rate_quality'] })
                
                influxPayload.append({
                    "measurement": "OUTLAND.Remote.Network.ConnectedDevices",
                    "tags": tags,
                    "time": now_iso(),
                    "fields": fields
                })
        if influxPayload:
            self.influx_sender(influxPayload, 'telegraf')

    def networkDHCPDevices(self):
        jsonDic = self.exec_syno_api('SYNO.Core.Network.DHCPServer.ClientList', 'list', '2', ifname='lbr0')
        result = jsonDic.get('data', {}).get('clientList', {}).get('ipv4', [])

        payload = []
        for item in result:   
            payload.append({
                "measurement": "OUTLAND.Remote.Network.DHCP",
                "tags": { "hostname":item['hostname'], "mac":item['clid'] },
                "time": now_iso(),
                "fields": { "expire":item['expire'], "internalIP":item['ip'] }
            })
        if payload:
            self.influx_sender(payload, 'telegraf')

    def networkWifiChannel(self):
        jsonDic = self.exec_syno_api('SYNO.Core.Network.Wifi.Hotspot', 'list', '2')
        result = jsonDic.get('data', [])

        payload = []
        for item in result:   
            payload.append({
                "measurement": "OUTLAND.Remote.Network.Wifi.Channels",
                "tags": { "netif":item['netif'] },
                "time": now_iso(),
                "fields": { "current_channel":item['current_channel'], "status":item['status'] }
            })
        if payload:
            self.influx_sender(payload, 'telegraf')

    def networkFirewallConnectionsLastDay(self):
        jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic.Domain', 'get_devices', '1', interval='day')
        result = jsonDic.get('data', [])

        totalConnections = sum(d['count'] for d in result if d) 
        payload = []
        for item in result:           
            userTotal = round((int((item['count']) * 100) / totalConnections), 1) if totalConnections > 0 else 0
            payload.append({
                "measurement": "OUTLAND.Remote.Network.FW.Summary.LastDay",
                "tags": { "hostname":item['hostname'] },
                "time": now_iso(),
                "fields": { "count":item['count'], "percentage":userTotal }
            })
        if payload:
            self.influx_sender(payload, 'telegraf')

    def networkFirewallBandwidthCheck(self, interval):
        jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic', 'get', '1', interval=interval, mode='net_l7')
        result = jsonDic.get('data', [])

        knowDevices = self.listKnowDevices()
        payload = []
        for item in result:           
            deviceName = findDeviceName(knowDevices, item['deviceID'])
            payload.append({
                "measurement": f"OUTLAND.Remote.Network.FW.Summary.Bandwidth.{interval}",
                "tags": { "hostname":deviceName },
                "time": now_iso(),
                "fields": { "download":item['download'], "download_packets":item['download_packets'], "upload":item['upload'], "upload_packets":item['upload_packets'] }
            })
        if payload:
            self.influx_sender(payload, 'telegraf')

    def networkFirewallDomainLastDay(self):
        jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic.Domain', 'get', '1', interval='day')
        result = jsonDic.get('data', [])

        payload = []
        for item in result:  
            if item['count'] > 5:      
                payload.append({
                    "measurement": "OUTLAND.Remote.Network.FW.Summary.Domain.day",
                    "tags": { "domainName":item['domainName'] },
                    "time": now_iso(),
                    "fields": { "count":item['count'], "domainId":item['domainId'] }
                })
        if payload:
            self.influx_sender(payload, 'telegraf')

    def networkFirewallUrlLive(self):
        jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic.Domain', 'get', '1', interval='live')
        result = jsonDic.get('data', [])
        knowDevices = self.listKnowDevices()

        payload = []
        for item in result:  
            try:
                ipData = socket.gethostbyname(item['domain'].split(':')[0])
            except:
                ipData = '0.0.0.0'

            if ipData != '0.0.0.0' and self.gi:
                try:
                    INFO = self.gi.city(ipData)
                    HASH = Geohash.encode(INFO.location.latitude, INFO.location.longitude)
                    location_name = INFO.city.name or INFO.country.iso_code or "Unknown"
                    country_code = INFO.country.iso_code or "Unknown"
                except:
                    HASH, location_name, country_code = "Unknown", "Unknown", "Unknown"
            else:
                HASH, location_name, country_code = "Blocked", "Blocked", "Blocked"

            parsedDateTime = datetime.fromtimestamp(float(item['timestamp']))
            if is_time(parsedDateTime):
                deviceName = findDeviceName(knowDevices, item['mac'])
                payload.append({
                    "measurement": "OUTLAND.Remote.Network.FW.Summary.Url.Live",
                    "tags": { "deviceName":deviceName, "country_code":country_code, "location_name":location_name, "geohash": HASH, "protocol":item['protocol'] },
                    "time": now_iso(),
                    "fields": { "detail":item['detail'], "domainName":item['domain'], "count": 1, "timestamp":parsedDateTime.strftime('%Y-%m-%d %H:%M:%S') }
                })
        if payload:
            self.influx_sender(payload, 'telegraf')

    def networkFirewallWebTraffic(self):
        jsonDic = self.exec_syno_api('SYNO.Core.NGFW.Traffic', 'get', '1', mode='net', interval='live')
        result = jsonDic.get('data', [])
        knowDevices = self.listKnowDevices()

        payload = []
        for item in result:  
            deviceName = findDeviceName(knowDevices, item['deviceID'])
            payload.append({
                "measurement": "OUTLAND.Remote.Network.FW.WebTraffic.Live",
                "tags": { "deviceName":deviceName },
                "time": now_iso(),
                "fields": { "download":item['download'], "upload":item['upload'] }
            })
        if payload:
            self.influx_sender(payload, 'telegraf')

    def getConnectionLogsOutland(self):
        jsonDic = self.exec_syno_api('SYNO.Core.SyslogClient.Log', 'list', '1', limit='100', target='LOCAL')
        result = jsonDic.get('data', {}).get('items', [])

        payload = []    
        for item in result:                 
            parsedDateTime = datetime.strptime(item['time'], '%Y/%m/%d %H:%M:%S')
            if is_time(parsedDateTime):
                logLevelInt = errorLvl(item['level'])   
                if 'failed' in item['descr']: logLevelInt = 3
                elif 'logged' in item['descr']: logLevelInt = 6

                payload.append({
                    "measurement": "OUTLAND.Remote.System.Logs.Connection",
                    "tags": { "user":item['who'], "logtype":item['logtype'], "level":item['level'], "timestamp":item['time'], 'orginalLogType':item['orginalLogType'], 'loglevelInt':logLevelInt },
                    "time": now_iso(),
                    "fields": { "descr":item['descr'] }
                })
        if payload:
            self.influx_sender(payload, 'telegraf')