import platform
import shutil
import subprocess
from json import loads as json_loads
from os import mkdir
from os.path import exists, isdir, isfile, join
from typing import Dict, List, Optional
from urllib.request import urlopen

from .fetch import queue_download_request, retrieve_bytes
from .output_directory import get_config_directory, get_temporary_directory
from .shell import (InteractiveSession, Progress, abort, pretty_debug,
                    pretty_warn, success)
from .utils import AttributeZipFile, remove_tree


def download_node(lts: bool = False) -> str:
	pretty_debug("Fetching Node.js versions...")
	version_index: List[Dict] = json_loads(retrieve_bytes("https://nodejs.org/dist/index.json"))
	if not isinstance(version_index, list):
		raise RuntimeError("Malformed Node.js dist/index.json file!")
	latest_version = None
	for version in version_index:
		if lts and "lts" not in version or not version["lts"]:
			continue
		latest_version = version["version"]
		break
	if not latest_version:
		raise RuntimeError(f"No suitable version in {len(version_index)} version(s) could be found!")

	system = platform.system().lower()
	if system == "windows":
		url = f"https://nodejs.org/dist/{latest_version}/node-{latest_version}-win-x64.zip"
	elif system == "darwin":
		url = f"https://nodejs.org/dist/{latest_version}/node-{latest_version}-darwin-x64.tar.gz"
	else:
		url = f"https://nodejs.org/dist/{latest_version}/node-{latest_version}-linux-x64.tar.gz"
	pretty_debug(f"Fetching Node.js {latest_version} from {url}...")

	archive_path = queue_download_request(url)
	if not archive_path:
		abort("Node.js cannot be installed or being cancelled.")
	node_dir = join(get_config_directory(), "node")

	with InteractiveSession(progress=Progress("Extracting Node.js...")):
		if archive_path.endswith(".zip"):
			with AttributeZipFile(archive_path, "r") as archive:
				archive.extractall(get_temporary_directory())
		else:
			import tarfile
			with tarfile.open(archive_path, "r:gz") as archive:
				archive.extractall(get_temporary_directory())

	import os
	extracted_folders = [f for f in os.listdir(get_temporary_directory()) if f.startswith("node-v20")]
	if not extracted_folders:
		raise RuntimeError("Failed to extract Node.js")

	extracted_dir = join(get_temporary_directory(), extracted_folders[0])
	remove_tree(node_dir)
	shutil.move(extracted_dir, node_dir)
	remove_tree(archive_path)

	success("Successfully downloaded and installed Node.js.")
	return node_dir

def request_typescript(only_check: bool = False) -> Optional[str]:
	"""
	Utility to check and install tsc with npm.
	"""
	from . import GLOBALS
	if GLOBALS.TOOLCHAIN_CONFIG.get_value("denyTypeScript"):
		return None
	from .shell import confirm_prompt, failure, pretty_debug
	from .utils import request_tool

	tsc = shutil.which("tsc") or request_tool("tsc")
	npm = shutil.which("npm")

	custom_node = GLOBALS.TOOLCHAIN_CONFIG.get_value("tools.node")
	from .output_directory import get_config_directory
	local_node = custom_node if custom_node else join(get_config_directory(), "node")

	if isdir(local_node):
		ext = ".cmd" if platform.system() == "Windows" else ""
		local_tsc = join(local_node, "tsc" + ext)
		if platform.system() != "Windows":
			local_tsc = join(local_node, "bin", "tsc")

		if isfile(local_tsc):
			tsc = local_tsc

		local_npm = join(local_node, "npm" + ext)
		if platform.system() != "Windows":
			local_npm = join(local_node, "bin", "npm")

		if isfile(local_npm):
			npm = local_npm

	if tsc or only_check:
		return tsc

	if not confirm_prompt("Do you want to enable TypeScript and ES6+ support (requires Node.js to build project)?", True):
		return None
	if not npm:
		pretty_debug("Node.js not found in system, downloading local instance...")
		download_node()
		return request_typescript(only_check=False)

	pretty_debug("Updating TypeScript via npm...")
	subprocess.run([npm, "install", "-g", "typescript"], shell=platform.system()=="Windows")
	tsc = shutil.which("tsc") or request_tool("tsc")

	if not tsc and isdir(local_node):
		ext = ".cmd" if platform.system() == "Windows" else ""
		tsc = join(local_node, "tsc" + ext)
		if platform.system() != "Windows":
			tsc = join(local_node, "bin", "tsc")

	if tsc:
		return tsc
	failure("Something went wrong when trying to install TypeScript Compiler, please check your Node.js and npm installation and try again.")
	return None

def fetch_declarations() -> bool:
	try:
		response = urlopen("https://nernar.github.io/declarations/core-engine.d.ts")
		declaration = response.read().decode("utf-8")
	except Exception as e:
		pretty_warn(f"Failed to fetch declarations: {e}")
		return False

	declaration_path = join(get_config_directory(), "declarations")
	if not exists(declaration_path):
		mkdir(declaration_path)
	with open(join(declaration_path, "core-engine.d.ts"), "w", encoding="utf-8") as file:
		file.write(declaration)
	commit_path = join(declaration_path, ".commit")
	if not isfile(commit_path):
		open(commit_path, "w").close()

	success("Installed latest version of core-engine.d.ts declarations.")
	return True
