import platform
import re
import struct
import subprocess
import sys
import zipfile
from os import environ, getenv, listdir, makedirs
from os.path import abspath, basename, exists, isdir, isfile, join, realpath
from typing import Any, Generator, List, Optional, Union

from . import GLOBALS
from .fetch import queue_download_request
from .shell import (InteractiveSession, Progress, abort, confirm_prompt, error,
                    info, pretty_print, pretty_print_failure,
                    pretty_print_success, warn)
from .utils import (AttributeZipFile, RuntimeCodeError, ensure_file,
                    ensure_not_whitespace, iterate_subdirectories,
                    read_properties_stream, remove_tree)

ABIS = {
	"armeabi-v7a": "arm",
	"arm64-v8a": "arm64",
	"x86": "x86",
	"x86_64": "x86_64"
}

FALLBACK_NDK_VERSIONS = {
	"armeabi-v7a": "16.1.4479499",
	"arm64-v8a": "21.4.7075529"
}

GCC_EXECUTABLES = dict()


def abi_to_arch(abi: str) -> str:
	if abi in ABIS:
		return ABIS[abi]
	raise ValueError(f"Unsupported ABI {abi!r}!")

def arch_to_abi(arch: str) -> str:
	for abi in ABIS:
		if arch == ABIS[abi]:
			return abi
	raise ValueError(f"Unsupported architecture {arch!r}!")

def ndk_version_to_revision(version: str) -> str:
	try:
		try:
			major, minor, patch = version.split(".", 3)
		except ValueError:
			major, minor = version.split(".", 2)
	except ValueError:
		major = version
		minor = "0"
	try:
		major = int(major)
		minor = int(minor)
	except ValueError as exc:
		raise RuntimeCodeError(1, "Invalid NDK Version: " + version + " (" + str(exc) + ")")
	suffix = "" if minor <= 0 else chr(97 + minor)
	return "r" + str(major) + suffix

def search_ndk_subdirectories(directory: str) -> Generator[str, Any, Any]:
	preferred_directory_regexes = [
		r"android-ndk-r\d+\b",
		r"android-ndk-.*",
		r"ndk[/\\]+\d+(\.\d+)+",
		"ndk-bundle"
	]
	for directory_regex in preferred_directory_regexes:
		compiled_pattern = re.compile(directory_regex + "$")
		for subdirectory in iterate_subdirectories(directory):
			if re.search(compiled_pattern, subdirectory):
				yield subdirectory

def search_unversioned_ndk_path(home_directory: str, contains_ndk: bool = False) -> Generator[str, Any, Any]:
	if contains_ndk:
		for ndk in search_ndk_subdirectories(home_directory):
			yield ndk
	try:
		android_tools = environ["ANDROID_SDK_ROOT"]
	except KeyError:
		android_tools = join(home_directory, "Android")
	if exists(android_tools):
		for ndk in search_ndk_subdirectories(android_tools):
			yield ndk
	android_tools = join(android_tools, "ndk")
	if exists(android_tools):
		for ndk in search_ndk_subdirectories(android_tools):
			yield ndk

def search_ndk_path(home_directory: str, contains_ndk: bool = False, ndk_version: Optional[str] = None) -> Optional[str]:
	for ndk_path in search_unversioned_ndk_path(home_directory, contains_ndk):
		if not ndk_version:
			return ndk_path
		package_version = read_ndk_source_version(ndk_path)
		if package_version:
			if "." not in ndk_version:
				package_version = package_version.split(".", 1)[0]
			if ndk_version == package_version:
				return ndk_path

def read_ndk_source_version(ndk_path: str) -> Optional[str]:
	properties_path = join(ndk_path, "source.properties")
	if not isfile(properties_path):
		return
	with open(properties_path, encoding="utf-8") as properties_file:
		properties = read_properties_stream(properties_file)
	try:
		return properties["Pkg.Revision"]
	except KeyError:
		pass

def get_ndk_path(ndk_version: Optional[str] = None) -> Optional[str]:
	relative_path = GLOBALS.TOOLCHAIN_CONFIG.get_value("native.ndkPath", GLOBALS.TOOLCHAIN_CONFIG.get_value("ndkPath"))
	if ensure_not_whitespace(relative_path):
		ndk_path = GLOBALS.TOOLCHAIN_CONFIG.get_path(relative_path)
		if not isdir(ndk_path):
			from .output_directory import get_config_directory
			ndk_path = join(get_config_directory(), relative_path)
		if isdir(ndk_path):
			return ndk_path
	# TODO: Rewrite to output_directory strategy...
	try:
		# Unix
		return search_ndk_path(environ["HOME"], ndk_version=ndk_version)
	except KeyError:
		pass
	# Windows
	return search_ndk_path(getenv("LOCALAPPDATA", "."), ndk_version=ndk_version)

def search_for_gcc_executable(ndk_directory: str) -> Optional[str]:
	search_directory = join(realpath(ndk_directory), "bin")
	if isdir(search_directory):
		pattern = re.compile(r"[0-9_A-Za-z]*-linux-android(eabi)*-g\+\+.*")
		files = listdir(search_directory)
		for filename in files:
			if re.match(pattern, filename):
				return abspath(join(search_directory, filename))
		pretty_print(f"Searching GCC in {search_directory} with {len(files)} files...")

def require_compiler_executable(arch: str, install_if_required: bool = False) -> Optional[str]:
	from .output_directory import get_config_directory
	ndk_directory = join(get_config_directory(), "ndk", arch)
	file = search_for_gcc_executable(ndk_directory)
	if install_if_required:
		install_gcc(arches=arch, reinstall=False)
		file = search_for_gcc_executable(ndk_directory)
		if not file or not isfile(file):
			warn(f"Executable of GCC (abi: {arch}) is not found, trying to reinstall it.")
			if install_gcc(arches=arch, reinstall=True) != 0:
				return None
			file = search_for_gcc_executable(ndk_directory)
			if not file or not isfile(file):
				error("Critical exception occured, installation is not supported anymore!")
				return None
	return file

def prepare_compiler_executable(abi: str) -> str:
	arch = abi_to_arch(abi)
	if arch in GCC_EXECUTABLES:
		return GCC_EXECUTABLES[arch]
	executable = require_compiler_executable(arch, install_if_required=True)
	if not executable:
		from .native_build import CODE_FAILED_NO_GCC
		raise RuntimeCodeError(CODE_FAILED_NO_GCC, f"Failed to acquire compiler executable from NDK for ABI {abi!r}!")
	GCC_EXECUTABLES[arch] = executable
	return executable

def check_installation(arches: Union[str, List[str]]) -> bool:
	if not isinstance(arches, list):
		arches = [arches]
	from .output_directory import get_config_directory
	return len(list(filter(
		lambda arch: not isfile(join(get_config_directory(), "ndk", f".installed-{arch}")),
		arches
	))) == 0

def get_download_ndk_url(revision: str) -> str:
	overriden_url = GLOBALS.TOOLCHAIN_CONFIG.get_value("native.ndkUrl", GLOBALS.TOOLCHAIN_CONFIG.get_value("ndkUrl"))
	if overriden_url and isinstance(overriden_url, str):
		return overriden_url
	pattern_version = re.search(r"\d+", revision)
	requires_architecture = pattern_version and int(pattern_version[0]) >= 11 and int(pattern_version[0]) <= 22
	is_32bit = struct.calcsize("P") == 4
	if is_32bit and (not pattern_version or requires_architecture or int(pattern_version[0]) >= 21):
		raise RuntimeCodeError(255, "Your platform is not supported anymore, you should upgrade to 64 bit for using Android NDK r21e and newer.")
	package_suffix = platform.system()
	if package_suffix == "Windows":
		if is_32bit or requires_architecture:
			package_suffix = "windows-x86" if is_32bit else "windows-x86_64"
		package_suffix = package_suffix or "windows"
	# TODO: Maybe also extract dmg archives from MacOS?
	elif package_suffix == "Darwin":
		package_suffix = "darwin-x86_64" if requires_architecture else "darwin"
	else:
		if is_32bit:
			raise RuntimeCodeError(255, f"Your platform {package_suffix} should be upgraded to 64 bit, otherwise Android NDK cannot be installed.")
		if package_suffix != "Linux":
			warn(f"* Expected platform Windows, MacOS or Linux. Got: {package_suffix}, falling back to Linux.")
		package_suffix = "linux-x86_64" if requires_architecture else "linux"
	return f"https://dl.google.com/android/repository/android-ndk-{revision}-{package_suffix}.zip"

def download_gcc(ndk_version: Optional[str] = None) -> Optional[str]:
	revision = ndk_version_to_revision(ndk_version) if ndk_version else "r16b"

	archive_path = queue_download_request(get_download_ndk_url(revision))
	if archive_path is None:
		return None

	with InteractiveSession(progress=Progress("Extracting NDK/GCC")) as session:
		from .output_directory import get_temporary_directory
		extract_path = join(get_temporary_directory(), f"ndk")
		makedirs(extract_path, exist_ok=True)
		try:
			with AttributeZipFile(archive_path, "r") as archive:
				archive.extractall(extract_path)
			pretty_print_success("Extracted NDK/GCC into temporary directory.")
		except OSError as exc:
			pretty_print_failure(f"#{exc.errno}: {basename(exc.filename)}")
			try:
				remove_tree(extract_path)
			except OSError:
				pretty_print_failure(f"#{exc.errno}: {basename(exc.filename)} (security fail)")
		except zipfile.BadZipFile as exc:
			try:
				remove_tree(extract_path)
				return download_gcc(revision)
			except OSError as exc:
				pretty_print_failure(f"#{exc.errno}: {basename(exc.filename)} (security fail)")

	return search_ndk_path(extract_path, contains_ndk=True, ndk_version=ndk_version)

def install_distutils_optionally() -> bool:
	try:
		try:
			from distutils.core import setup  # type: ignore
			return True
		except ImportError:
			pass
		pip_output = subprocess.run([
			"pip3" if platform.system() != "Windows" else "pip",
			"install", "setuptools"
		], capture_output=True, text=True)
		setuptools_installed = pip_output.returncode == 0
		if setuptools_installed:
			info("Dependency distutils for Android NDK successfully installed!")
		else:
			warn("Android NDK requires distutils dependency in order to work, but installation went wrong:")
			warn(pip_output.stderr.strip())
		return setuptools_installed
	except OSError:
		pass
	return False

def download_and_make_standalone_toolchain(arch: str, reinstall: bool = False) -> int:
	abi = arch_to_abi(arch)
	ndk_version = GLOBALS.PREFERRED_CONFIG.get_value("native.ndkVersions." + abi)
	if not ndk_version and abi in FALLBACK_NDK_VERSIONS:
		ndk_version = FALLBACK_NDK_VERSIONS[abi]
	ndk_path = get_ndk_path(ndk_version=ndk_version)

	if not ndk_path:
		if not reinstall:
			pretty_print(f"Not found valid NDK installation for {abi}.")
		question = "Install NDK from Android Repository?"
		if ndk_version:
			question = f"Install NDK {ndk_version} from Android Repository?"
		if reinstall or confirm_prompt(question, True):
			ndk_path = download_gcc(ndk_version=ndk_version)
		else:
			abort()

	if not ndk_path:
		error("Installation interrupted by raised cause above, you are must extract 'temp/ndk-r**.zip' manually into temp and retry task.")
		return 1

	with InteractiveSession(progress=Progress(f"Making standalone toolchain of {abi}...", percentage=0.5)) as session:
		from .output_directory import get_config_directory
		output = subprocess.run([
			"python3" if platform.system() != "Windows" else "python",
			join(ndk_path, "build", "tools", "make_standalone_toolchain.py"),
			"--arch", arch,
			"--api", "21" if "64" in arch else "19",
			"--install-dir", join(get_config_directory(), "ndk", arch),
			"--force"
		], capture_output=True, text=True)
		if output.returncode != 0:
			error(output.stderr.strip())
			pretty_print_failure(f"Failed to make a standalone toolchain for {abi} architecture with code {output.returncode}!")
			return output.returncode
		else:
			ensure_file(join(get_config_directory(), "ndk", f".installed-{arch}"))
			pretty_print_success(f"Now native builds are available for {arch} architecture.")
	return output.returncode

def install_gcc(arches: Union[str, List[str]] = "arm", reinstall: bool = False) -> int:
	if not reinstall and check_installation(arches):
		return 0

	setuptools_troubleshoot = install_distutils_optionally()
	if not isinstance(arches, list):
		arches = [arches]

	result = 0
	for arch in arches:
		result = download_and_make_standalone_toolchain(arch, reinstall=reinstall)
		if result != 0:
			break

	try:
		if result == 0:
			from .output_directory import get_temporary_directory
			remove_tree(join(get_temporary_directory(), "network"))
	except OSError as exc:
		pass

	if result != 0:
		if setuptools_troubleshoot:
			if sys.version_info > (3, 11):
				troubleshoot = "To use Android NDK starting with Python 3.12 requires installation of distutils dependency."
			else:
				troubleshoot = "Your Python installation does not contain distutils dependency needed to run Android NDK."
			warn(troubleshoot, "We were unable to do this automatically, so you can try following options to solve problem:")
			if platform.system() == 'Windows':
				warn(" - pip install setuptools")
				warn(" - python -m pip install setuptools")
			else:
				warn(" - apt-get install python-setuputils")
				warn(" - pacman -S python-setuputils")
				warn(" - pip3 install setuptools")
				warn(" - python3 -m pip install setuptools")
			warn(f"Visit https://docs.python.org/3/library/distutils.html for details.")
		else:
			warn("Please use a different version of Android NDK or report this issue to developer.")
	return result
