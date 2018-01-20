from tippiLink import TippiLink

import rumps
import subprocess
from subprocess import Popen, PIPE
import os.path
import json
import re

rumps.debug_mode(True)

app = None

_CONF_LOCATION = os.path.join(os.path.expanduser("~"), ".sharfoo.conf")
_TEMPLATE = """{
"username": "admin",
"password": "admin",
"host": "192.168.0.1"
}
"""


def _send_os_notification(message, title="", subtitle=""):
    # Workaround to send notificaitons because notifications in rumps are broken
    # https://github.com/jaredks/rumps/issues/59

    cmd = b"""display notification "%s" with title "%s" Subtitle "%s" """ % (message, title, subtitle)
    Popen(["osascript", '-'], stdin=PIPE, stdout=PIPE).communicate(cmd)


def _get_bssid():
    output = subprocess.check_output(
        ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"]
    )
    matches = re.match('.*BSSID: (.*?)\n', output, re.DOTALL)
    is_on = True
    if output == "AirPort: Off\n":
        is_on = False
        bssid = None
    else:
        bssid = matches.group(1)
    return is_on, bssid


def _read_admin_credentials():
    with open(_CONF_LOCATION) as f:
        x = f.read()

    creds = json.loads(x)
    return creds["username"], creds["password"], creds["host"], creds["bssid"] if "bssid" in creds else None


def _update_config_file(username, password, host, bssid):
    d = {
        "username": username,
        "password": password,
        "host": host,
        "bssid": bssid
    }
    with open(_CONF_LOCATION, "w") as f:
        f.write(json.dumps(d, sort_keys=True, indent=4, separators=(',', ': ')))


def _create_template_file():
    if os.path.isfile(_CONF_LOCATION):
        return False

    with open(_CONF_LOCATION, "w") as f:
        f.write(_TEMPLATE)

    return True


def _are_credentials_valid(username, password, host):
    tl = TippiLink(username, password, host)
    try:
        tl.get_connected_clients()
        return True
    except:
        return False


class Sharfoo(rumps.App):
    def __init__(self):
        super(Sharfoo, self).__init__("Initializing")
        self.menu = ["Restart router"]
        self.connected_mac = set()
        self.mac_to_name = dict()
        self.mac_to_ip = dict()
        if _create_template_file():
            rumps.alert("Created config file",
                        "Please enter router admin credentials in %s and press OK" % _CONF_LOCATION)

        username, password, host, self.bssid = _read_admin_credentials()
        if self.bssid is None:
            while True:
                if _are_credentials_valid(username, password, host):
                    break
                else:
                    rumps.alert("Invalid credentials, please update and click OK")
                    username, password, host, _ = _read_admin_credentials()

            _, self.bssid = _get_bssid()
            _update_config_file(username, password, host, self.bssid)

        self.tl = TippiLink(username, password, host)

    def _clear_data(self):
        for conn in self.connected_mac:
            del self.menu[self.mac_to_name[conn]]
        self.connected_mac = set()
        self.mac_to_ip = dict()
        self.mac_to_name = dict()

    @rumps.timer(5)
    def update_title(self, _):
        try:
            is_on, connected_bssid = _get_bssid()

            if not is_on:
                self.title = "Wifi Off"
                self._clear_data()
                return

            if connected_bssid != self.bssid:
                self.title = "Roaming"
                self._clear_data()
                return

            try:
                clients = self.tl.get_connected_clients()
            except:
                self.title = "No Access"
                return

            # TODO: Parse MAC adresses to identify make and model
            total = len(clients)
            print "Connected: %d" % total
            self.title = "Connected: %d" % total

            for client in clients:
                self.mac_to_name[client['mac_address']] = client['client_name']
                self.mac_to_ip[client['mac_address']] = client['ip']

            if len(self.connected_mac) > 0:  # Skip on first run
                current_macs = {client['mac_address'] for client in clients}
                new_joined = current_macs - self.connected_mac
                new_left = self.connected_mac - current_macs

                for joined in new_joined:
                    self.menu.add(self.mac_to_name[joined])
                    _send_os_notification(self.mac_to_name[joined] + "\n" + self.mac_to_ip[joined], "Joined Wifi")

                for left in new_left:
                    del self.menu[self.mac_to_name[left]]
                    _send_os_notification(self.mac_to_name[left] + "\n" + self.mac_to_ip[left], "Left Wifi")
            else:  # Run only first time
                self.menu = [client['client_name'] for client in clients]

            self.connected_mac = {client["mac_address"] for client in clients}

        except Exception as e:
            print e
            self.title = "<ERROR 101>"

    @rumps.clicked("Restart router")
    def restart_router(self, _):
        print "Restarting router"
        self.title = "Restarting router"
        self.tl.restart_router()

if __name__ == "__main__":
    app = Sharfoo().run()
