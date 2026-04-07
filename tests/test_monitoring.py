import importlib.util
import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from datetime import time

def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    # Patch geoip2 Reader during import to avoid missing file errors
    with patch('geoip2.database.Reader'):
        spec.loader.exec_module(module)
    return module

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
router_path = os.path.join(BASE_DIR, 'Monitor-Router.py')
internet_path = os.path.join(BASE_DIR, 'Monitor-Internet.py')

router = import_file('Monitor_Router', router_path)
internet = import_file('Monitor_Internet', internet_path)

# --- Monitor-Router Tests ---

def test_router_error_lvl():
    assert router.errorLvl("info") == 1
    assert router.errorLvl("warn") == 2
    assert router.errorLvl("error") == 3
    assert router.errorLvl("other") is None

def test_router_find_device_name():
    devices = [{"mac": "00:AA:11", "hostname": "Desktop"}]
    assert router.findDeviceName(devices, "00:AA:11") == "Desktop"
    assert router.findDeviceName(devices, "FF:FF:FF") is None

def test_router_is_time_between():
    # Normal range
    assert router.is_time_between(time(10, 0), time(12, 0), time(11, 0)) is True
    # Midnight crossing
    assert router.is_time_between(time(23, 0), time(1, 0), time(0, 30)) is True
    # Outside range
    assert router.is_time_between(time(10, 0), time(12, 0), time(13, 0)) is False

def test_router_list_known_devices(mocker):
    mocker.patch('Monitor_Router.exec_syno_api', return_value={'data': [{'mac': '123', 'hostname': 'host'}]})
    devices = router.listKnowDevices()
    assert len(devices) == 1
    assert devices[0]['mac'] == '123'

# --- Monitor-Internet Tests ---

def test_internet_collector_init(mocker):
    mock_config = mocker.patch('Monitor_Internet.configManager')
    mock_config.return_value.output = False
    mock_config.return_value.test_server = []
    
    mocker.patch('Monitor_Internet.InfluxDBClient')
    mock_speedtest = mocker.patch('speedtest.Speedtest')
    
    collector = internet.InfluxdbSpeedtest(config='config_internet.ini')
    assert collector.output is False
    mock_speedtest.assert_called_once()

def test_internet_config_manager_logic(tmp_path, mocker):
    # Create a temporary config file
    config_file = tmp_path / "config_internet.ini"
    config_file.write_text("[GENERAL]\nDelay=5\nOutput=True\n[INFLUXDB]\nUrl=http://localhost\nToken=t\nOrg=o\nBucket=b\nVerify_SSL=True\n[SPEEDTEST]\nServer=123")
    
    mocker.patch('os.path.isfile', return_value=True)
    # Mock configparser to read the string instead of real file
    mocker.patch('os.path.join', return_value=str(config_file))
    
    cfg = internet.configManager(config="config_internet.ini")
    assert cfg.delay == 5
    assert cfg.influx_url == "http://localhost"
    assert cfg.test_server == ["123"]