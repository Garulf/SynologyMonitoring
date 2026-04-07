from datetime import timezone, datetime, timedelta

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat()

def errorLvl(argument):
    switcher = {
        "info": 1,
        "warn": 2,
        "error": 3,
    }
    return switcher.get(argument)

def findDeviceName(jsonDic, deviceMac):
    if not jsonDic:
        return None
    for item in jsonDic:
        if item['mac'] == deviceMac:
            return item['hostname']
    return None

def is_time_between(begin_time, end_time, check_time=None):
    check_time = check_time or datetime.utcnow().time()
    if begin_time < end_time:
        return check_time >= begin_time and check_time <= end_time
    else: # crosses midnight
        return check_time >= begin_time or check_time <= end_time

def is_time(eventTime):
    nowDateTime = datetime.now() - timedelta(seconds=30)
    return eventTime >= nowDateTime