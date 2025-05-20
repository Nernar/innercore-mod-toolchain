import re
from hashlib import md5
from os import environ
from os.path import join, splitext
from typing import NamedTuple

from .utils import encode_int

# (numeric part, major version, minor version), (stage part, stage, patch number), (commit part, commit/date, timezone)
GRADLE_VERSION_REGEX = re.compile(r"((\d+)(\.\d+)+)(-([^\W\d_]+)-(\w+))?(-(SNAPSHOT|\d{14}([-+]\d{4})?))?")

class GradleVersion(NamedTuple):
	version: str
	comparable: float
	snapshot: bool

def get_gradle_home() -> str:
	gradle_home = environ.get("GRADLE_USER_HOME")
	if gradle_home is None:
		from .output_directory import get_user_directory
		gradle_home = join(get_user_directory(), ".gradle")
	return gradle_home

def parse_gradle_specification(version: str) -> GradleVersion:
	if version == "latest" or version == "nightly" or version == "release-nightly" or version == "release-candidate":
		return GradleVersion(version, 0.0, version != "latest" and version != "release-candidate")

	spec = GRADLE_VERSION_REGEX.fullmatch(version)
	if spec is None:
		raise ValueError(f"Specify a valid Gradle release listed on https://gradle.org/releases/. Got: {version!r}.")

	comparable = float(spec.group(2) + spec.group(3))
	snapshot = spec.group(5) in ("snapshot", "commit") or spec.group(8) is not None
	return GradleVersion(spec.string, comparable, snapshot)

def get_gradle_distribution_url(spec: GradleVersion, type: str = "bin") -> str:
	repository = "distributions" if not spec.snapshot else "distributions-snapshots"
	return f"https://services.gradle.org/{repository}/gradle-{spec.version}-{type}.zip"

def url_as_gradle_checksum(url: str) -> str:
	ascii_url = bytes(url, "ascii")
	md5_hash = md5(ascii_url).digest()
	md5_checksum = int.from_bytes(md5_hash)
	return encode_int(md5_checksum, 36)

def url_to_local_gradle_distribution(url: str) -> str:
	try:
		archive_path_index = url.rindex("/")
		archive_path = url[archive_path_index + 1:]
	except ValueError:
		archive_path = url

	archive_name = splitext(archive_path)[0]
	url_checksum = url_as_gradle_checksum(url)
	return join("wrapper", "dists", archive_name, url_checksum, archive_path)
