from os import listdir
from os.path import basename, exists, isdir, join
from typing import Callable, List, Optional

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
