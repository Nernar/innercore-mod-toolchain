import platform
import re
import socket
import subprocess
from os.path import basename, isdir, isfile, join, relpath
from typing import Any, Dict, List, Optional, Tuple

from . import GLOBALS
from .hglob import glob
from .shell import (InteractiveSession, Progress, abort, confirm_prompt, error,
                    pretty_print, pretty_print_attention, pretty_print_failure,
                    pretty_print_success, select_prompt, warn)
from .utils import DEVNULL


def get_adb_executable() -> str:
	try:
		import shutil
		if shutil.which("adb"):
			return "adb"
	except:
		pass
	from .output_directory import get_config_directory
	if platform.system() == "Windows":
		return join(get_config_directory(), "adb", "adb.exe")
	return join(get_config_directory(), "adb", "adb")

def get_modpack_push_directory() -> Optional[str]:
	directory = GLOBALS.PREFERRED_CONFIG.get_value("pushTo", allow_prototype=False)
	if not directory:
		directory = GLOBALS.TOOLCHAIN_CONFIG.get_value("pushTo")
		if directory:
			if not GLOBALS.is_project_available() or not GLOBALS.MAKE_CONFIG.current_project:
				return None
			directory = join(directory, "mods", basename(GLOBALS.MAKE_CONFIG.current_project)) if "/horizon/packs/" in directory \
				else join(directory, basename(GLOBALS.MAKE_CONFIG.current_project))

	if not directory:
		GLOBALS.TOOLCHAIN_CONFIG.set_value("pushTo", setup_modpack_directory())
		if not GLOBALS.PREFERRED_CONFIG.get_value("pushTo"):
			abort("Not found any modpacks, nothing to do.")
		GLOBALS.TOOLCHAIN_CONFIG.save_as_file()
		return get_modpack_push_directory()

	if "/horizon/packs/" not in directory and not GLOBALS.PREFERRED_CONFIG.get_value("adb.pushAnyLocation", False):
		pretty_print(
			f"Push directory {directory} looks suspicious, it does not belong to Horizon packs directory. " +
			"This action may easily corrupt all content inside, allow it only if you know what are you doing."
		)
		which = select_prompt(
			"What will you do?",
			"Choice another modpack",
			"Push it anyway",
			"No questions, always push",
			"Nothing", fallback=3
		)

		if which == 0:
			GLOBALS.TOOLCHAIN_CONFIG.delete_value("pushTo")
			if GLOBALS.TOOLCHAIN_CONFIG != GLOBALS.PREFERRED_CONFIG:
				GLOBALS.PREFERRED_CONFIG.delete_value("pushTo")
			return get_modpack_push_directory()
		elif which == 2:
			GLOBALS.TOOLCHAIN_CONFIG.set_value("adb.pushAnyLocation", True)
			GLOBALS.TOOLCHAIN_CONFIG.save_as_file()
			pretty_print("This may be changed in your 'toolchain.json' config.")
		elif which == 3:
			pretty_print("Pushing aborted.")
			return None

	return directory

def ls_packs_on_remote(path: str) -> List[str]:
	directories = []
	if test_directory_exist(path + "/innercore/mods"):
		directories.append(path + "/innercore")
	return directories + [path + "/modpacks/" + directory for directory in ls(path + "/modpacks")[0] \
		if test_directory_exist(path + "/modpacks/" + directory + "/mods")]

def person_readable_modpack_name(path: str) -> str:
	what = path.split("/")[::-1]
	try:
		suffix = " (internal)" if "Android/data" in path else ""
		if what[0] == "com.mojang":
			return "Legacy Core Engine" + suffix
		if what[0] == "innercore":
			return what[1] + suffix
		if what[3] == "packs":
			return f"{basename(path)} in {what[2]}" + suffix
		return "/".join(what[0:2][::-1]) + suffix
	except IndexError:
		pass
	return basename(path)

def get_sdcard_directory() -> Optional[str]:
	locations = GLOBALS.TOOLCHAIN_CONFIG.get_value("storageLocations")
	if not locations or len(locations) == 0:
		locations = ["/storage/emulated/0", "/mnt/sdcard", "/sdcard"]
	for location in locations:
		if test_directory_exist(location):
			return location
	if test_directory_exist("/storage/emulated"):
		directories = ls("/storage/emulated")[0]
		for directory in directories:
			if test_directory_exist("/storage/emulated/" + directory):
				return "/storage/emulated/" + directory
	return None

def setup_modpack_directory() -> Optional[str]:
	locations = GLOBALS.TOOLCHAIN_CONFIG.get_value("modpackLocations")
	if not locations or len(locations) == 0:
		locations = ["games/horizon/packs", "Android/data/com.zheka.horizon/files/horizon/packs"]
	sdcard_directory = get_sdcard_directory()
	if not sdcard_directory:
		error("We were unable to find storage folder on your device.")
		error("Please override `storageLocations` property in your 'toolchain.json' to override path.")
		return None
	directories = set()
	for location in locations:
		modpack_directory = sdcard_directory + "/" + location
		directories.update(ls_packs_on_remote(modpack_directory))
		for relative_directory in ls(modpack_directory)[0]:
			directories.update(ls_packs_on_remote(modpack_directory + "/" + relative_directory))
	if test_directory_exist(sdcard_directory + "/games/com.mojang/mods"):
		directories.add(sdcard_directory + "/games/com.mojang")
	if len(directories) == 0:
		error("It looks like your device does not contain an Inner Core installation.")
		error("Please install pack via Horizon or override `modpackLocations` property of your 'toolchain.json'.")
		return None
	directories = list(directories)
	readable_directories = [person_readable_modpack_name(directory) for directory in directories]
	which = select_prompt("Which modpack will be used?", *readable_directories)
	return None if which is None else directories[which]

def test_directory_exist(path: str, *args: str) -> bool:
	try:
		subprocess.run(GLOBALS.ADB_COMMAND + [
			"shell", "test", "-d", path
		] + list(args), check=True)
	except subprocess.CalledProcessError as err:
		if err.returncode != 1:
			error("adb shell test -d failed with code", err.returncode)
		return False
	return True

def ls(path: str, *args: str) -> Tuple[List[str], List[str]]:
	try:
		pipe = subprocess.run(GLOBALS.ADB_COMMAND + [
			"shell", "ls", "-F", path
		] + list(args), text=True, check=True, capture_output=True)
	except subprocess.CalledProcessError as err:
		if err.returncode != 1:
			error("adb shell ls failed with code", err.returncode)
		return (list(), list())
	except KeyboardInterrupt:
		return (list(), list())
	files, directories = list(), list()
	for partition in (entry.partition(" ") for entry in pipe.stdout.rstrip().splitlines()):
		is_directory = (len(partition[2]) != 0 and partition[0] == "d") or partition[0][-1] == "/"
		filename = partition[2] if len(partition[2]) > 0 else partition[0][:-1] if partition[0][-1] == "/" else partition[0]
		(directories if is_directory else files).append(filename)
	return directories, files

def push_everything(push_unchanged: bool = True, cleanup_remote: bool = True) -> int:
	destination_directory = get_modpack_push_directory()
	if not destination_directory:
		return 1
	push_unchanged = GLOBALS.PREFERRED_CONFIG.get_value("adb.pushUnchangedFiles", push_unchanged)
	cleanup_remote = GLOBALS.PREFERRED_CONFIG.get_value("adb.cleanupRemote", cleanup_remote)

	result = push_directory(GLOBALS.MOD_STRUCTURE.directory, destination_directory, push_unchanged=push_unchanged, cleanup_remote=cleanup_remote)
	if result > 0:
		return result
	for linked_resource in GLOBALS.LINKED_RESOURCE_STORAGE.iterate_resources():
		project_path = GLOBALS.MAKE_CONFIG.get_relative_path(linked_resource["relative_path"])
		remote_path = destination_directory + "/" + linked_resource["output_path"]
		remote_push_unchanged = linked_resource["push_unchanged"] if "push_unchanged" in linked_resource else push_unchanged
		remote_cleanup_remote = linked_resource["cleanup_remote"] if "cleanup_remote" in linked_resource else cleanup_remote
		if isfile(project_path):
			result = push_file(project_path, remote_path, push_unchanged=remote_push_unchanged, cleanup_remote=remote_cleanup_remote) or result
		elif isdir(project_path):
			result = push_directory(project_path, remote_path, push_unchanged=remote_push_unchanged, cleanup_remote=remote_cleanup_remote) or result
		else:
			pretty_print()
			abort(f"We cannot push {linked_resource['relative_path']!r} resource because we could not determine its type!")
		if result > 0:
			return result
	if result < 0:
		pretty_print_success("All files already up to date.")

	GLOBALS.OUTPUT_STORAGE.save()
	return 0

def push_file(file: str, destination_file: str, push_unchanged: bool = True, cleanup_remote: bool = True) -> int:
	if not push_unchanged and not GLOBALS.OUTPUT_STORAGE.is_path_changed(file):
		return -1

	readable_name = basename(file)
	with InteractiveSession(progress=Progress(f"Pushing file {readable_name}")) as session:
		destination_file = destination_file.replace("\\", "/")
		if not destination_file.startswith("/"):
			destination_file = "/" + destination_file
		sources_file = file.replace("\\", "/")
		# try:
		if cleanup_remote:
			subprocess.call(GLOBALS.ADB_COMMAND + [
				"shell", "rm", "-r", destination_file
			], stderr=DEVNULL, stdout=DEVNULL)
		result = subprocess.run(GLOBALS.ADB_COMMAND + [
			"push", sources_file, destination_file
		], capture_output=True, text=True)
		# XXX: except KeyboardInterrupt:
			# Progress.notify(shell, progress, 1, "Pushing aborted.")
			# return 1

		if result.returncode != 0:
			cause = result.stdout.splitlines()[-1]
			if cause and len(cause) > 0:
				error(cause)
			pretty_print_failure(f"Failed to push file {readable_name!r} with error code {result.returncode}!")
			return result.returncode

	pretty_print_success(f"Pushed file {readable_name!r} into {destination_file!r}.")
	return result.returncode

def push_directory(directory: str, destination_directory: str, push_unchanged: bool = True, cleanup_remote: bool = True) -> int:
	items = [
		relpath(path, directory) for path in glob(directory + "/*") \
			if push_unchanged or GLOBALS.OUTPUT_STORAGE.is_path_changed(path)
	]
	files_count = len(items)
	if files_count == 0:
		return -1

	readable_name = basename(directory)
	with InteractiveSession(progress=Progress(f"Pushing {readable_name}/")) as session:
		destination_directory = destination_directory.replace("\\", "/")
		if not destination_directory.startswith("/"):
			destination_directory = "/" + destination_directory
		sources_directory = directory.replace("\\", "/")

		offset = 0
		for filename in items:
			src = sources_directory + "/" + filename
			dst = destination_directory + "/" + filename
			session["progress"].update(offset / files_count, f"Pushing {readable_name}/{filename}")
			# try:
			if cleanup_remote:
				subprocess.call(GLOBALS.ADB_COMMAND + [
					"shell", "rm", "-r", dst
				], stderr=DEVNULL, stdout=DEVNULL)
			result = subprocess.run(GLOBALS.ADB_COMMAND + [
				"push", src, dst
			], capture_output=True, text=True)
			# XXX: except KeyboardInterrupt:
				# Progress.notify(shell, progress, 1, "Pushing aborted.")
				# return 1
			offset += 1

			if result.returncode != 0:
				cause = result.stdout.strip().splitlines()[-1]
				if cause and len(cause) > 0:
					error(cause)
				pretty_print_failure(f"Failed to push directory {readable_name!r} with error code {result.returncode}!")
				return result.returncode

	pretty_print_success(f"Pushed directory {readable_name!r} into {destination_directory!r}.")
	return 0

def make_locks(*locks: str) -> int:
	destination_directory = get_modpack_push_directory()
	if not destination_directory:
		return -1

	for lock in locks:
		lock = join(destination_directory, lock).replace("\\", "/")
		result = subprocess.call(GLOBALS.ADB_COMMAND + [
			"shell", "touch", lock
		])
		if result != 0:
			return result
	return 0

def ensure_server_running(retry: int = 0) -> bool:
	try:
		subprocess.run([
			get_adb_executable(),
			"start-server"
		], check=True, stdout=DEVNULL, stderr=DEVNULL)
		return True
	except subprocess.CalledProcessError as err:
		if retry >= 3:
			error("adb start-server failed with code", err.returncode)
			return False
		return ensure_server_running(retry + 1)

STATE_UNKNOWN = -1
STATE_DEVICE_CONNECTED = 0
STATE_NO_DEVICES = 1
STATE_DISCONNECTED = 2
STATE_DEVICE_AUTHORIZING = 3

def which_state(what: Optional[str] = None) -> int:
	if what is None:
		return STATE_UNKNOWN
	try:
		return {
			"no devices": STATE_NO_DEVICES,
			"device": STATE_DEVICE_CONNECTED,
			"authorizing": STATE_DEVICE_AUTHORIZING
		}[what]
	except KeyError: # offline
		return STATE_DISCONNECTED

def get_device_state() -> int:
	try:
		pipe = subprocess.run([
			get_adb_executable(),
			"get-state"
		], text=True, timeout=3.0, check=True, capture_output=True)
	except subprocess.CalledProcessError as err:
		if err.returncode == 1:
			return STATE_NO_DEVICES
		error("adb get-state failed with code", err.returncode)
		return STATE_UNKNOWN
	except subprocess.TimeoutExpired:
		return STATE_UNKNOWN
	return which_state(pipe.stdout.strip())

def get_device_serial() -> Optional[str]:
	try:
		pipe = subprocess.run([
			get_adb_executable(),
			"get-serialno"
		], text=True, check=True, capture_output=True)
	except subprocess.CalledProcessError as err:
		warn("adb get-serialno failed with code", err.returncode)
		return None
	return pipe.stdout.strip()

def device_list() -> Optional[List[Dict[str, Any]]]:
	try:
		pipe = subprocess.run([
			get_adb_executable(),
			"devices", "-l"
		], text=True, check=True, capture_output=True)
	except subprocess.CalledProcessError as err:
		warn("adb devices failed with code", err.returncode)
		return None
	data = pipe.stdout.rstrip().splitlines()
	data.pop(0)
	devices = list()
	for device in data:
		device = re.split(r"\s+", device)
		devices.append({
			"serial": device[0],
			"state": which_state(device[1]),
			"data": device[2:]
		})
	return devices

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

def get_ip() -> str:
	make = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	make.settimeout(0)
	try:
		make.connect(("10.253.254.255", 1))
		ip = make.getsockname()[0]
	except Exception:
		ip = "127.0.0.1"
	finally:
		make.close()
	return ip

def get_adb_command() -> List[str]:
	ensure_server_running()
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
				pretty_print(f"Connection to {target} timeout")
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

def get_adb_command_by_serial(serial: str) -> List[str]:
	ensure_server_running()
	devices = GLOBALS.TOOLCHAIN_CONFIG.get_value("devices", list())
	if not serial in devices:
		try:
			from ipaddress import ip_address
			ip_address(serial.partition(":")[0])
		except ValueError:
			devices.append(serial)
			GLOBALS.TOOLCHAIN_CONFIG.set_value("devices", devices)
			GLOBALS.TOOLCHAIN_CONFIG.save_as_file()
	return [
		get_adb_executable(),
		"-s", serial
	]

def get_adb_command_by_tcp(ip: str, port: Optional[int] = None, skip_error: bool = False) -> Optional[List[str]]:
	ensure_server_running()
	if not get_adb_command_by_serialno_type("-e", silent=skip_error):
		if skip_error or not confirm_prompt("Are you sure want to save it?", False):
			return None
	device: dict[str, Any] = {
		"ip": ip
	}
	if port:
		device["port"] = port
	devices = GLOBALS.TOOLCHAIN_CONFIG.get_value("devices", list())
	if not device in devices:
		devices.append(device)
		GLOBALS.TOOLCHAIN_CONFIG.set_value("devices", devices)
		GLOBALS.TOOLCHAIN_CONFIG.save_as_file()
	return [
		get_adb_executable(),
		"-e"
	]

def get_adb_command_by_serialno_type(which: str, silent: bool = False) -> Optional[List[str]]:
	serial = subprocess.run([
		get_adb_executable(),
		which, "get-serialno"
	], text=True, capture_output=True)
	if serial.returncode != 0:
		if not silent:
			warn("adb get-serialno failed with code", serial.returncode)
		return None
	return get_adb_command_by_serial(serial.stdout.rstrip())

def setup_device_connection() -> Optional[List[str]]:
	not_connected_any_device = len(GLOBALS.TOOLCHAIN_CONFIG.get_value("devices", list())) == 0
	if not_connected_any_device:
		pretty_print(
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
		pretty_print("Listening device via cable...")
		pretty_print(f"* Press Ctrl+{'C' if platform.system() == 'Windows' else 'Z'} to leave")
		subprocess.run([
			get_adb_executable(),
			"wait-for-usb-device"
		], check=True, timeout=90.0, stdout=DEVNULL, stderr=DEVNULL)
		command = get_adb_command_by_serialno_type("-d")
		if command:
			return command
	except subprocess.CalledProcessError as err:
		error("adb wait-for-usb-device failed with code", err.returncode)
	except subprocess.TimeoutExpired:
		pretty_print("Timeout")
	except KeyboardInterrupt:
		pretty_print()
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
		pretty_print("Not available right now.")
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
		# XXX: except KeyboardInterrupt:
			# return setup_via_network()

		if len(accepted) == 0:
			pretty_print_attention("Not found anything, are you sure that network is connected?")
			return setup_via_network()
		subprocess.run([
			get_adb_executable(),
			"disconnect"
		], stdout=DEVNULL, stderr=DEVNULL)
		pretty_print("Found connections: " + ", ".join(accepted))

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
					pretty_print()
			except subprocess.CalledProcessError as err:
				error("adb connect failed with code", err.returncode)
			except subprocess.TimeoutExpired:
				pretty_print("Timeout")

		if latest:
			return latest
		pretty_print_attention("Pinging every port, interrupt operation if you already know it.")
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

def ping_via_shell(ip: str, index: int, progress: Optional[Progress] = None) -> int:
	if progress and index % 15 == 0:
		progress.update(index / 255, f"Pinging {ip}")
	return subprocess.call([
		"ping",
		"-n" if platform.system() == "Windows" else "-c", "1",
		ip
	], stdout=DEVNULL, stderr=DEVNULL) == 0

async def ping(ip: str, index: int, accepted: List[str], progress: Optional[Progress] = None) -> None:
	if progress and index % 15 == 0:
		progress.update(index / 255, f"Pinging {ip}")
	import asyncio
	coroutine = await asyncio.create_subprocess_shell(
		f"ping {'-n' if platform.system() == 'Windows' else '-c'} 1 {ip}", stdout=DEVNULL, stderr=DEVNULL
	)
	await coroutine.wait()
	if coroutine.returncode == 0:
		accepted.append(ip)

async def ping_async(ip: Tuple[str, str, str], accepted: List[str], progress: Optional[Progress] = None) -> None:
	import asyncio
	tasks = list()
	for index in range(256):
		if str(index) == ip[2]:
			continue
		next_ip = "{}.{}".format(ip[0], index)
		task = asyncio.ensure_future(ping(next_ip, index, accepted, progress=progress))
		tasks.append(task)
	await asyncio.gather(*tasks, return_exceptions=True)

async def connect(ip: str, port: int, accepted: List[str], progress: Optional[Progress] = None) -> None:
	if len(accepted) > 0:
		return
	if progress and port % 15 == 0:
		progress.update(port / 65535, f"Connecting to {ip}:{str(port)}")
	import asyncio
	coroutine = await asyncio.create_subprocess_shell(
		get_adb_executable() + " connect " + ip + ":" + str(port), stdout=DEVNULL, stderr=DEVNULL
	)
	await coroutine.wait()
	if coroutine.returncode == 0:
		accepted.append(str(port))

async def connect_async(ip: str, accepted: List[str], progress: Optional[Progress] = None) -> None:
	import asyncio
	tasks = list()
	for index in range(1000, 65536):
		task = asyncio.ensure_future(connect(ip, index, accepted, progress=progress))
		tasks.append(task)
	await asyncio.gather(*tasks, return_exceptions=True)

def setup_via_tcp_network(ip: Optional[str] = None, port: Optional[str] = None, pairing_code: Optional[str] = None, with_pairing_code: bool = False) -> Optional[List[str]]:
	if not ip:
		pretty_print("You are connected via", get_ip())
		try:
			tcp = input("Specify address: IP[:PORT] ")
			if len(tcp) == 0:
				return setup_via_network()
		except KeyboardInterrupt:
			pretty_print()
			return setup_via_network()
		tcp = tcp.split(":")
		ip = tcp[0]
		port = tcp[1] if len(tcp) > 1 else port
	if with_pairing_code or pairing_code:
		if not pairing_code:
			try:
				pairing_code = input("Specify pairing code: ")
			except KeyboardInterrupt:
				pretty_print()
				return setup_via_network()
		try:
			subprocess.run([
				get_adb_executable(),
				"pair",
				f"{ip}:{port}" if port else ip,
				pairing_code
			], check=True, stderr=DEVNULL, stdout=DEVNULL)
		except subprocess.CalledProcessError as err:
			error("adb pair failed with code", err.returncode)
		except KeyboardInterrupt:
			pretty_print()
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
		error("adb connect failed with code", err.returncode)
	except subprocess.TimeoutExpired:
		pretty_print("Timeout")
	except KeyboardInterrupt:
		pretty_print()
	return setup_via_network()

def setup_externally(skip_input: bool = False) -> Optional[List[str]]:
	state = get_device_state()
	if state == STATE_DEVICE_CONNECTED or state == STATE_DEVICE_AUTHORIZING:
		serial = get_device_serial()
		if serial:
			if not serial in GLOBALS.TOOLCHAIN_CONFIG.get_value("devices", list()):
				return get_adb_command_by_serial(serial)
			else:
				pretty_print("Connected device already saved, maybe another available too.")
	else:
		pretty_print("Not found connected devices, resolving everything...")
	devices = device_list()
	if not devices:
		return setup_device_connection()
	device = which_device_will_be_connected(*devices, state_not_matter=True)
	if not device:
		pretty_print("Nope, nothing to perform here.")
		if not skip_input:
			try:
				input()
			except KeyboardInterrupt:
				pretty_print()
		return setup_device_connection()
	return get_adb_command_by_serial(device["serial"])

def setup_how_to_use() -> Optional[List[str]]:
	pretty_print(
		"Android Debug Bridge (adb) is a versatile command-line tool that lets you communicate with a device. " +
		"The adb command facilitates a variety of device actions, such as installing and debugging apps, " +
		"and it provides access to a Unix shell that you can use to run a variety of commands on a device."
	)
	pretty_print("https://developer.android.com/studio/command-line/adb")
	try:
		input()
	except KeyboardInterrupt:
		pretty_print()
	return setup_device_connection()
