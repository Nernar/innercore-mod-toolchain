import platform
import subprocess
from os.path import basename, isfile, join, relpath
from typing import List

from .context import GLOBALS
from .logger import attention, debug, failure, frozen
from .utils import ensure_file_directory

try:
	from hashlib import blake2s as _encode
except ImportError:
	from hashlib import md5 as _encode


def source_path_to_cache(source_file: str, cache_dir: str) -> str:
	name_hash = _encode(source_file.encode("utf-8")).hexdigest()[:16]
	return join(cache_dir, name_hash + ".js")

def execute_babel(babel: str, source: str, out_file: str, config_file: str, extensions: str = ".ts,.js") -> int:
	command = [
		babel,
		source,
		"--out-file", out_file,
		"--config-file", config_file,
		"--extensions", extensions,
		"--no-babelrc", # Ignoring existing configurations, since we are passing it anyways
	]
	return subprocess.call(command, shell=platform.system() == "Windows")

def transpile_with_babel(ordered_files: List[str], output_path: str, babel_config_path: str, source_directory: str, force: bool = False) -> int:
	from .babel_setup import request_babel
	babel = request_babel()
	if not babel:
		raise RuntimeError("Babel CLI is required to transpile this source. Make sure it is installed.")

	cache_dir = GLOBALS.MAKE_CONFIG.get_build_path(join("sources", "babel_cache"))
	ensure_file_directory(join(cache_dir, ".keep"))

	any_changed = False

	for source_file in ordered_files:
		if not isfile(source_file):
			attention(f"Source file {source_file!r} not found, skipping.")
			continue

		cache_js = source_path_to_cache(source_file, cache_dir)
		changed = force or GLOBALS.BUILD_STORAGE.is_path_changed(source_file) or not isfile(cache_js)

		if changed:
			debug(f"Transpiling {basename(source_file)!r} with Babel")
			result = execute_babel(babel, source_file, cache_js, babel_config_path)
			if result != 0:
				failure(f"Babel failed on {basename(source_file)!r} with code {result}.")
				return result
			any_changed = True
		else:
			frozen(f"{basename(source_file)!r} is not changed.")

	if any_changed or not isfile(output_path):
		ensure_file_directory(output_path)
		with open(output_path, "w", encoding="utf-8") as out:
			first = True
			for source_file in ordered_files:
				cache_js = source_path_to_cache(source_file, cache_dir)
				if not isfile(cache_js):
					attention(f"Cache for {basename(source_file)!r} not found after compilation, skipping.")
					continue
				if not first:
					out.write("\n\n")
				rel = relpath(source_file, source_directory).replace("\\", "/")
				out.write(f"// file: {rel}\n\n")
				out.write(open(cache_js, encoding="utf-8").read().strip())
				first = False
	else:
		frozen(f"Build target {basename(output_path)!r} is not changed.")

	return 0
