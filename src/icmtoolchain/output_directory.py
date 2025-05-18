import platform
from functools import lru_cache
from os import environ, listdir
from os.path import basename, exists, expanduser, isdir, join, normpath
from typing import Callable, List, Optional

from .utils import ensure_not_whitespace

try:
	from hashlib import blake2s as encode
except ImportError:
	from hashlib import md5 as encode

def unique_folder_name(path: str) -> str:
	return basename(path) + "-" + encode(bytes(path, "utf-8")).hexdigest()[-5:]

def expand_paths(file_or_directory: str, filter: Optional[Callable[[str], bool]] = None) -> List[str]:
	locations = list()
	if len(file_or_directory) > 0 and file_or_directory[-1] == "*":
		if not isdir(file_or_directory):
			return locations
		for filename in listdir(file_or_directory):
			file = join(file_or_directory, filename)
			if not filter or filter(file):
				locations.append(file)
	else:
		if exists(file_or_directory) and (not filter or filter(file_or_directory)):
			locations.append(file_or_directory)
	return locations

def get_windows_appdata(csidl: int, env_variable: str, shell_name: str) -> str:
	try:
		import ctypes
	except ImportError:
		pass
	else:
		if hasattr(ctypes, "windll"):
			buffer = ctypes.create_unicode_buffer(1024)
			windll = getattr(ctypes, "windll")
			windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buffer)

			# Downgrade to short path name if it has high-bit chars.
			if any(ord(c) > 255 for c in buffer):
				shortest_buffer = ctypes.create_unicode_buffer(1024)
				if windll.kernel32.GetShortPathNameW(buffer.value, shortest_buffer, 1024):
					buffer = shortest_buffer

			return buffer.value

	try:
		import winreg
	except ImportError:
		result = environ.get(env_variable)
		if result is None:
			raise ValueError(f"Unset environment variable: {env_variable}")
		return result
	else:
		key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
		directory, _ = winreg.QueryValueEx(key, shell_name)
		return str(directory)

@lru_cache(maxsize=2048)
def get_user_config_directory(*components: str) -> str:
	if platform.system() == "Windows":
		appdata_path = get_windows_appdata(26, "APPDATA", "AppData")
		return join(normpath(appdata_path), *components)
	path = environ.get("XDG_DATA_HOME", "")
	if not ensure_not_whitespace(path):
		if platform.system() == "Darwin":
			path = expanduser("~/Library/Application Support")
		else:
			path = expanduser("~/.config")
	return join(path, *components)

def get_config_directory() -> str:
	return get_user_config_directory("icmtoolchain")

@lru_cache(maxsize=2048)
def get_user_temporary_directory(*components: str) -> str:
	if platform.system() == "Windows":
		appdata_path = get_windows_appdata(28, "LOCALAPPDATA", "Local AppData")
		return join(normpath(appdata_path), *components, "Cache")
	path = environ.get("XDG_CACHE_HOME", "")
	if not ensure_not_whitespace(path):
		if platform.system() == "Darwin":
			path = expanduser("~/Library/Caches")
		else:
			path = expanduser("~/.cache")
	return join(path, *components)

def get_temporary_directory() -> str:
	return get_user_temporary_directory("icmtoolchain")
