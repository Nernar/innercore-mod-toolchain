from .context import GLOBALS
import platform
import subprocess
from typing import Any, Dict, List, Optional

from .shell import select_prompt, InteractiveSession, Progress
from .logger import print, attention, failure
from .errors import abort
from .utils import DEVNULL
from .adb import (
	get_adb_executable, ensure_server_running, get_device_state, 
	wait_for_authorization, get_adb_command_by_serial, 
	get_adb_command_by_tcp, get_adb_command_by_serialno_type, 
	device_list, STATE_DEVICE_CONNECTED, STATE_DEVICE_AUTHORIZING
)
from .network import get_ip, ping_async, ping_via_shell, connect_async


def person_readable_device_name(device: Dict[str, Any]) -> str:
	if "data" in device:
		for property in device["data"]:
			what = property.partition(":")
			if what[0] == "model":
				return f"{device['serial']} ({what[2]})"
	return device["serial"]

def which_device_will_be_connected(*devices: Dict[str, Any], state_not_matter: bool = False) -> Optional[Dict[str, Any]]:
	connected = [device for device in devices
		if device["state"] == STATE_DEVICE_CONNECTED
		or device["state"] == STATE_DEVICE_AUTHORIZING
		or state_not_matter]
	if len(connected) < 2:
		return None if len(connected) == 0 else connected[0]
	which = select_prompt("Which device will be used?", *[
		person_readable_device_name(device) for device in connected
	] + ["I doesn't see my device"])
	return None if which is None or which == len(connected) else connected[which]

def setup_device_connection() -> Optional[List[str]]:
	not_connected_any_device = len(GLOBALS.TOOLCHAIN_CONFIG.get_value("devices", list())) == 0
	if not_connected_any_device:
		print(
			"Howdy! " +
			"Before starting we're must set up your devices, don't you think so? " +
			"Let's configure some connections."
		)
	which = select_prompt("How connection will be performed?", *[
		"I've connected device via cable",
		"Over air/network will be best",
		"Everything already performed"
	] + (["Wha.. I don't understand!"] if not_connected_any_device else list()) + [
		"It will be performed later"
	], fallback=3 + (1 if not_connected_any_device else 0))
	return setup_via_usb() if which == 0 else \
		setup_via_network() if which == 1 else \
		setup_externally() if which == 2 else \
		setup_how_to_use() if which == 3 and \
			not_connected_any_device else None

def setup_via_usb() -> Optional[List[str]]:
	try:
		print("Listening device via cable...")
		attention(f"Press Ctrl+{'C' if platform.system() == 'Windows' else 'Z'} to leave")
		subprocess.run([
			get_adb_executable(),
			"wait-for-usb-device"
		], check=True, timeout=90.0, stdout=DEVNULL, stderr=DEVNULL)
		command = get_adb_command_by_serialno_type("-d")
		if command:
			return command
	except subprocess.CalledProcessError as err:
		failure("adb wait-for-usb-device failed with code", err.returncode)
	except subprocess.TimeoutExpired:
		print("Timeout")
	except KeyboardInterrupt:
		print()
	return setup_device_connection()

def setup_via_network() -> Optional[List[str]]:
	which = select_prompt(
		"Which network type must be used?",
		"Just TCP by IP and PORT",
		"Ping network automatically",
		"Connect with pairing code",
		"Turn back", fallback=3
	)
	return setup_device_connection() if which == 3 else \
		setup_via_ping_localhost() if which == 1 else \
		setup_via_tcp_network(with_pairing_code=which == 2)

def setup_via_ping_localhost() -> Optional[List[str]]:
	ip = get_ip().rpartition(".")
	if len(ip[2]) == 0:
		print("Not available right now.")
		return setup_via_network()

	with InteractiveSession(progress=Progress("Connecting...")) as session:
		accepted = list()
		try:
			import asyncio
			asyncio.run(ping_async(ip, accepted, progress=session["progress"]))
		except ImportError:
			for index in range(256):
				if str(index) == ip[2]:
					continue
				next_ip = "{}.{}".format(ip[0], index)
				if ping_via_shell(next_ip, index, progress=session["progress"]):
					accepted.append(next_ip)

		if len(accepted) == 0:
			attention("Not found anything, are you sure that network is connected?")
			return setup_via_network()
		subprocess.run([
			get_adb_executable(),
			"disconnect"
		], stdout=DEVNULL, stderr=DEVNULL)
		print("Found connections: " + ", ".join(accepted))

		latest = None
		for next in accepted:
			try:
				subprocess.run([
					get_adb_executable(),
					"connect", next
				], check=True, timeout=5.0, stdout=DEVNULL, stderr=DEVNULL)
				command = get_adb_command_by_tcp(next, skip_error=True)
				if command:
					latest = command
					break
				else:
					print()
			except subprocess.CalledProcessError as err:
				failure("adb connect failed with code", err.returncode)
			except subprocess.TimeoutExpired:
				print("Timeout")

		if latest:
			return latest
		attention("Pinging every port, interrupt operation if you already know it.")
		for next in accepted:
			ports = list()
			try:
				import asyncio
				asyncio.run(connect_async(next, ports, progress=session["progress"]))
			except ImportError:
				pass
			for port in ports:
				command = get_adb_command_by_tcp(next + ":" + port, skip_error=True)
				if command:
					latest = command
					break

	return latest or setup_via_network()

def setup_via_tcp_network(ip: Optional[str] = None, port: Optional[str] = None, pairing_code: Optional[str] = None, with_pairing_code: bool = False) -> Optional[List[str]]:
	if not ip:
		print("You are connected via", get_ip())
		try:
			tcp = input("Specify address: IP[:PORT] ")
			if len(tcp) == 0:
				return setup_via_network()
		except KeyboardInterrupt:
			print()
			return setup_via_network()
		parts = tcp.split(":")
		ip = parts[0]
		port = parts[1] if len(parts) > 1 else port
	if with_pairing_code or pairing_code:
		if not pairing_code:
			try:
				pairing_code = input("Specify pairing code: ")
			except KeyboardInterrupt:
				print()
				return setup_via_network()
		try:
			subprocess.run([
				get_adb_executable(),
				"pair",
				f"{ip}:{port}" if port else ip,
				pairing_code
			], check=True, stderr=DEVNULL, stdout=DEVNULL)
		except subprocess.CalledProcessError as err:
			failure("adb pair failed with code", err.returncode)
		except KeyboardInterrupt:
			print()
	subprocess.run([
		get_adb_executable(),
		"disconnect"
	], stdout=DEVNULL, stderr=DEVNULL)
	try:
		subprocess.run([
			get_adb_executable(),
			"connect",
			f"{ip}:{port}" if port else ip
		], check=True, timeout=10.0, stdout=DEVNULL, stderr=DEVNULL)
		command = get_adb_command_by_tcp(ip, int(port) if port else None)
		return command or setup_via_tcp_network()
	except subprocess.CalledProcessError as err:
		failure("adb connect failed with code", err.returncode)
	except subprocess.TimeoutExpired:
		print("Timeout")
	except KeyboardInterrupt:
		print()
	return setup_via_network()

def setup_externally(skip_input: bool = False) -> Optional[List[str]]:
	state = get_device_state()
	from .adb import get_device_serial
	if state == STATE_DEVICE_CONNECTED or state == STATE_DEVICE_AUTHORIZING:
		serial = get_device_serial()
		if serial:
			if not serial in GLOBALS.TOOLCHAIN_CONFIG.get_value("devices", list()):
				return get_adb_command_by_serial(serial)
			else:
				print("Connected device already saved, maybe another available too.")
	else:
		print("Not found connected devices, resolving everything...")
	devices = device_list()
	if not devices:
		return setup_device_connection()
	device = which_device_will_be_connected(*devices, state_not_matter=True)
	if not device:
		print("Nope, nothing to perform here.")
		if not skip_input:
			try:
				input()
			except KeyboardInterrupt:
				print()
		return setup_device_connection()
	return get_adb_command_by_serial(device["serial"])

def setup_how_to_use() -> Optional[List[str]]:
	print(
		"Android Debug Bridge (adb) is a versatile command-line tool that lets you communicate with a device. " +
		"The adb command facilitates a variety of device actions, such as installing and debugging apps, " +
		"and it provides access to a Unix shell that you can use to run a variety of commands on a device."
	)
	print("https://developer.android.com/studio/command-line/adb")
	try:
		input()
	except KeyboardInterrupt:
		print()
	return setup_device_connection()

def get_adb_command() -> List[str]:
	ensure_server_running()
	if get_device_state() == STATE_DEVICE_AUTHORIZING:
		wait_for_authorization()
	if get_device_state() == STATE_DEVICE_CONNECTED:
		return [get_adb_executable()]
	devices = GLOBALS.TOOLCHAIN_CONFIG.get_value("devices", list())
	if len(devices) > 0:
		subprocess.run([
			get_adb_executable(),
			"disconnect"
		], stdout=DEVNULL, stderr=DEVNULL)
	for device in devices:
		if isinstance(device, dict):
			target = f"{device['ip']}:{device['port']}" if "port" in device else device["ip"]
			try:
				subprocess.run([
					get_adb_executable(),
					"connect", target
				], timeout=3.0, stdout=DEVNULL, stderr=DEVNULL)
			except subprocess.TimeoutExpired:
				print(f"Connection to {target} timeout")
	pending = device_list()
	if pending:
		itwillbe = list()
		for device in pending:
			if device["serial"] in devices:
				itwillbe.append(device)
		device = which_device_will_be_connected(*(pending if len(itwillbe) == 0 else itwillbe))
		if device:
			return get_adb_command_by_serial(device["serial"])
	if GLOBALS.PREFERRED_CONFIG.get_value("adb.doNothingIfDisconnected", False):
		abort("Not found connected devices, nothing to do.")
	which = setup_externally(True) if len(devices) > 0 else setup_device_connection()
	if which is None:
		abort("Nothing will happen, adb set up interrupted.")
	return which
