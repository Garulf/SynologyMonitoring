import configparser
import os
import sys

class ConfigManager:
    def __init__(self, config_path):
        self.config = configparser.ConfigParser()
        config_file = os.path.join(os.getcwd(), config_path)
        if not os.path.isfile(config_file):
            print(f'Warning: Config file {config_file} not found. Falling back to environment variables.')
        else:
            self.config.read(config_file)

        # InfluxDB
        self.influx_url = os.getenv('INFLUX_URL', self.config.get('INFLUXDB', 'Url', fallback=None))
        self.influx_token = os.getenv('INFLUX_TOKEN', self.config.get('INFLUXDB', 'Token', fallback=None))
        self.influx_org = os.getenv('INFLUX_ORG', self.config.get('INFLUXDB', 'Org', fallback=None))
        self.influx_bucket = os.getenv('INFLUX_BUCKET', self.config.get('INFLUXDB', 'Bucket', fallback='telegraf'))
        self.influx_verify_ssl = os.getenv('INFLUX_VERIFY_SSL', str(self.config.getboolean('INFLUXDB', 'Verify_SSL', fallback=True))).lower() == 'true'

        # SSH
        self.ssh_host = os.getenv('SSH_HOST', self.config.get('SSH', 'Host', fallback=None))
        self.ssh_user = os.getenv('SSH_USER', self.config.get('SSH', 'User', fallback='admin'))
        self.ssh_key = os.getenv('SSH_KEY_PATH', self.config.get('SSH', 'KeyPath', fallback='/app/id_rsa'))