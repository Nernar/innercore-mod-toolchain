from .context import GLOBALS
import platform
import re
import shutil
from hashlib import md5, sha256
from os import environ, walk
from os.path import basename, dirname, isdir, isfile, join, splitext
from typing import NamedTuple, Optional

from .fetch import queue_download_request, retrieve_bytes
from .output_directory import (FileLock, get_config_directory,
                               get_temporary_directory)
from .shell import InteractiveSession, Progress, abort, success
from .utils import AttributeZipFile, encode_int, ensure_directory, remove_tree

# (numeric part, major version, minor version), (stage part, stage, patch number), (commit part, commit/date, timezone)
GRADLE_VERSION_REGEX = re.compile(r"((\d+)(\.\d+)+)(-([^\W\d_]+)-(\w+))?(-(SNAPSHOT|\d{14}([-+]\d{4})?))?")
COMPARABLE_VERSION_REGEX = re.compile(r"(\d+)\.(\d+)")

class GradleVersion(NamedTuple):
	version: str
	major: int
	minor: int
	snapshot: bool

def find_gradle_home() -> str:
	gradle_home = environ.get("GRADLE_USER_HOME")
	if gradle_home is None:
		from .output_directory import get_user_directory
		gradle_home = join(get_user_directory(), ".gradle")
	return gradle_home

def parse_gradle_specification(version: str) -> GradleVersion:
	if version == "latest" or version == "nightly" or version == "release-nightly" or version == "release-candidate":
		return GradleVersion(version, 0, 0, version != "latest" and version != "release-candidate")

	spec = GRADLE_VERSION_REGEX.fullmatch(version)
	if spec is None:
		raise ValueError(f"Specify a valid Gradle release listed on https://gradle.org/releases/. Got: {version!r}.")
	comparable_spec = COMPARABLE_VERSION_REGEX.match(spec.group(1))
	assert comparable_spec

	snapshot = spec.group(5) in ("snapshot", "commit") or spec.group(8) is not None
	return GradleVersion(spec.string, int(comparable_spec.group(1)), int(comparable_spec.group(2)), snapshot)

def get_gradle_distribution_url(spec: GradleVersion, type: str = "bin") -> str:
	repository = "distributions" if not spec.snapshot else "distributions-snapshots"
	return f"https://services.gradle.org/{repository}/gradle-{spec.version}-{type}.zip"

def url_as_gradle_checksum(url: str) -> str:
	ascii_url = bytes(url, "ascii")
	md5_hash = md5(ascii_url).digest()
	md5_checksum = int.from_bytes(md5_hash, "big")
	return encode_int(md5_checksum, 36)

def url_to_local_gradle_distribution(url: str) -> str:
	try:
		archive_path_index = url.rindex("/")
		archive_path = url[archive_path_index + 1:]
	except ValueError:
		archive_path = url

	archive_name = splitext(archive_path)[0]
	url_checksum = url_as_gradle_checksum(url)
	return join(archive_name, url_checksum, archive_path)

def get_user_gradle_disribution(relative_path: str) -> str:
	return join(find_gradle_home(), "wrapper", "dists", relative_path)

def verify_gradle_installation(archive_path: str, without_marker: bool = False) -> Optional[str]:
	distribution_directory = dirname(archive_path)
	marker_file = join(distribution_directory, f"{basename(archive_path)}.ok")
	if not isdir(distribution_directory) or (not without_marker and not isfile(marker_file)):
		return None
	for dirpath, dirnames, filenames in walk(distribution_directory, followlinks=True):
		for relative_path in dirnames:
			gradle_home = join(dirpath, relative_path)
			if find_gradle_launcher(gradle_home):
				return gradle_home
			break

def find_gradle_launcher(gradle_home: str) -> Optional[str]:
	executable_directory = join(gradle_home, "lib")
	if not isdir(executable_directory):
		return None
	for dirpath, dirnames, filenames in walk(executable_directory, followlinks=True):
		for relative_path in filenames:
			if relative_path[:16] == "gradle-launcher-" and relative_path[-4:] == ".jar":
				return join(dirpath, relative_path)

def verify_gradle_remote_checksum(archive_path: str, url: str) -> bool:
	if not isfile(archive_path):
		return False
	local_hash = sha256()
	with open(archive_path, "rb") as file:
		while True:
			chunk = file.read(4096)
			if not chunk:
				break
			local_hash.update(chunk)
	remote_hash = str(retrieve_bytes(url), encoding="ascii")
	return remote_hash == local_hash.hexdigest()

def download_gradle_version(archive_path: str, url: str) -> str:
	distribution_directory = dirname(archive_path)
	ensure_directory(distribution_directory)
	marker_file = join(distribution_directory, f"{basename(archive_path)}.ok")

	remove_tree(marker_file)
	for dirpath, dirnames, filenames in walk(distribution_directory, followlinks=True):
		for relative_path in dirnames:
			remove_tree(join(dirpath, relative_path))

	if not verify_gradle_remote_checksum(archive_path, f"{url}.sha256"):
		remove_tree(archive_path)
		queue_download_request(url, output_path=archive_path)
		if not verify_gradle_remote_checksum(archive_path, f"{url}.sha256"):
			raise ValueError(f"SHA256 mismatch, failed to confirm validity of {basename(archive_path)} archive!")
	with AttributeZipFile(archive_path, "r") as archive:
		archive.extractall(distribution_directory)

	gradle_home = verify_gradle_installation(archive_path, without_marker=True)
	if not gradle_home:
		raise ValueError(f"Unsupported distribution {basename(archive_path)}, please retry task with different version!")
	open(marker_file, "x").close()
	remove_tree(archive_path)
	return gradle_home

def resolve_gradle_version(version: str) -> str:
	gradle_specification = parse_gradle_specification(version)
	distribution_url = get_gradle_distribution_url(gradle_specification)
	local_path = url_to_local_gradle_distribution(distribution_url)
	archive_path = get_user_gradle_disribution(local_path)

	with FileLock(f"{archive_path}.lck", delete=False):
		from time import sleep
		sleep(2)
		gradle_home = verify_gradle_installation(archive_path)
		if not gradle_home:
			gradle_home = download_gradle_version(archive_path, distribution_url)
	return gradle_home

def download_jdk() -> str:
	system = platform.system().lower()
	if system == "windows":
		url = "https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u412-b08/OpenJDK8U-jdk_x64_windows_hotspot_8u412b08.zip"
	elif system == "darwin":
		url = "https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u412-b08/OpenJDK8U-jdk_x64_mac_hotspot_8u412b08.tar.gz"
	else:
		url = "https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u412-b08/OpenJDK8U-jdk_x64_linux_hotspot_8u412b08.tar.gz"

	archive_path = queue_download_request(url)
	if not archive_path:
		abort("JDK cannot be installed or being cancelled.")
	jdk_dir = join(get_config_directory(), "java")

	with InteractiveSession(progress=Progress("Extracting JDK...")):
		if archive_path.endswith(".zip"):
			with AttributeZipFile(archive_path, "r") as archive:
				archive.extractall(get_temporary_directory())
		else:
			import tarfile
			with tarfile.open(archive_path, "r:gz") as archive:
				archive.extractall(get_temporary_directory())

	import shutil
	from os import listdir
	extracted_folders = [f for f in listdir(get_temporary_directory()) if f.startswith("jdk8u") or f.startswith("jdk")]
	if not extracted_folders:
		raise RuntimeError("Failed to extract JDK!")

	extracted_dir = join(get_temporary_directory(), extracted_folders[0])
	if system == "darwin" and isdir(join(extracted_dir, "Contents", "Home")):
		extracted_dir = join(extracted_dir, "Contents", "Home")

	remove_tree(jdk_dir)
	shutil.move(extracted_dir, jdk_dir)
	remove_tree(archive_path)

	success("Successfully downloaded and installed JDK 8.")
	return jdk_dir

def get_jdk_executable(executable: str = "java", install_allowed: bool = True) -> str:
	pass

	custom_path = GLOBALS.TOOLCHAIN_CONFIG.get_value("tools.jdk", GLOBALS.TOOLCHAIN_CONFIG.get_value("java.jdkPath"))
	ext = ".exe" if platform.system() == "Windows" else ""
	if custom_path:
		custom_exe = join(custom_path, "bin", f"{executable}{ext}")
		if isfile(custom_exe):
			return custom_exe

	sys_path = shutil.which(executable)
	if sys_path:
		return sys_path

	local_path = join(get_config_directory(), "java", "bin", f"{executable}{ext}")
	if isfile(local_path):
		return local_path

	if install_allowed:
		download_jdk()
		if isfile(local_path):
			return local_path

	raise RuntimeError(f"Could not find or install {executable}. Please install JDK 1.8.")
