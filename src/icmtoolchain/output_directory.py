from os.path import basename

try:
	from hashlib import blake2s as encode
except ImportError:
	from hashlib import md5 as encode

def unique_folder_name(path: str) -> str:
	return basename(path) + "-" + encode(bytes(path, "utf-8")).hexdigest()[-5:]
