from dataclasses import dataclass
from itertools import chain
from os.path import basename, exists, isdir, isfile, join, relpath, splitext
from time import time
from typing import Any, List, MutableMapping, Optional, Tuple

from .context import GLOBALS, PROPERTIES
from .includes import Includes
from .language import MakeScriptData
from .logger import attention, debug, failure, frozen, print, success
from .output_directory import expand_paths
from .script_setup import request_typescript
from .utils import (RuntimeCodeError, copy_file, ensure_not_whitespace,
                    walk_all_files)


@dataclass
class DirectorySource:
	includes: Includes
	destination_path: str
	language: str

@dataclass
class FileSource:
	source_path: str
	destination_path: str
	language: str

def build_all_scripts() -> int:
	GLOBALS.PROJECT_STRUCTURE.cleanup_target("scripts")
	GLOBALS.PROJECT_STRUCTURE.cleanup_target("libraries")

	if request_typescript(only_check=True) and not isdir(GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("declarations")):
		from .output_directory import get_config_directory
		if not isdir(join(get_config_directory(), "declarations")):
			attention("Not found 'declarations', in most cases build will be failed, please install it via tasks.")

	return build_composite_project()

def declare_build_target(source: MakeScriptData, target_path: str) -> str:
	declare: MutableMapping[str, Any] = {
		# make.json source type -> build.config source type
		"sourceType": "mod" if source.type == "main" else "custom" if source.type == "instant" else source.type
	}

	if ensure_not_whitespace(source.api) and source.type != "preloader":
		declare["api"] = source.api
	if source.optimization_level != -1:
		declare["optimizationLevel"] = min(max(int(source.optimization_level), -1), 9)
	if ensure_not_whitespace(source.source_name):
		declare["sourceName"] = source.source_name

	target_type = "libraries" if source.type == "library" else "scripts"
	return GLOBALS.PROJECT_STRUCTURE.declare_target(
		keyword=target_type,
		relative_path=target_path,
		declare=declare
	).absolute_path

def detect_source_language(source_path: str) -> Optional[str]:
	detected_javascript = False
	detected_typescript = False

	if not isdir(source_path):
		detected_javascript = source_path.endswith(".js")
		detected_typescript = source_path.endswith(".ts") and not source_path.endswith(".d.ts")

	else:
		def walk(file: str) -> None:
			nonlocal detected_javascript
			if file.endswith(".ts") and not file.endswith(".d.ts"):
				raise ValueError()
			if not detected_javascript and file.endswith(".js"):
				detected_javascript = True

		try:
			walk_all_files(source_path, walk)
		except ValueError:
			detected_typescript = True

	if not (detected_javascript or detected_typescript):
		return None
	return "typescript" if detected_typescript else "javascript"

def compute_and_capture_changed_scripts() -> Tuple[List[FileSource], List[FileSource], List[DirectorySource], List[DirectorySource]]:
	changed_files = []
	files = []
	changed_directories = []
	directories = []

	for source in GLOBALS.MAKE_CONFIG.iterate_scripts():
		includes_path = ensure_not_whitespace(source.includes_path, ".includes")
		is_pattern_path = source.relative_path.endswith("*")

		for source_path in expand_paths(GLOBALS.MAKE_CONFIG.get_relative_path(source.relative_path)):
			if not exists(source_path):
				attention(f"Skipped non-existing source {GLOBALS.MAKE_CONFIG.get_path_to_config(source_path)!r}!")
				continue

			# Supports assembling directories, JavaScript and TypeScript
			detected_language = detect_source_language(source_path)
			if not detected_language:
				attention(f"Unsupported script {GLOBALS.MAKE_CONFIG.get_path_to_config(source_path)!r}, it should be directory with includes or Java/TypeScript file!")
				continue

			# Developer can deny to install TypeScript/Node.js or forcefully deny it
			language = ensure_not_whitespace(source.language, detected_language)
			if language == "typescript" and not request_typescript():
				if detected_language == "typescript" and GLOBALS.TOOLCHAIN_CONFIG.get_value("denyTypeScript"):
					raise RuntimeCodeError(255, f"We cannot compile source {GLOBALS.MAKE_CONFIG.get_path_to_config(source_path)!r} without you having Node.js, despite `denyTypeScript` property of your 'toolchain.json' is being active. Please disable it and install Node.js to compile TypeScript sources.")
				attention(f"Source {GLOBALS.MAKE_CONFIG.get_path_to_config(source_path)!r} specifies target language as TypeScript, so this script probably uses ESNext capabilities. Building as normal JavaScript files, since `denyTypeScript` property of your 'toolchain.json' is active.")
				language = "javascript"

			if not is_pattern_path:
				prefixed_path = source.output_path
			else:
				script_name = basename(source_path)
				if isfile(source_path):
					script_name = splitext(script_name)[0]
				prefixed_path = join(source.output_path, script_name + ".js")

			# Preserve output target duplication
			try:
				dot_index = prefixed_path.rindex(".")
				prefixed_path = prefixed_path[:dot_index] + "{}" + prefixed_path[dot_index:]
			except ValueError:
				prefixed_path += "{}"

			destination_path = declare_build_target(source, prefixed_path)

			if isdir(source_path):
				includes = Includes.invalidate(source_path, includes_path)
				if includes.compute(destination_path, language):
					changed_directories.append(DirectorySource(includes, destination_path, language))
				directories.append(DirectorySource(includes, destination_path, language))

			elif isfile(source_path):
				if GLOBALS.BUILD_STORAGE.is_path_changed(source_path) or (language == "typescript" and not isfile(
					join(GLOBALS.MAKE_CONFIG.get_build_path("sources"), relpath(source_path, GLOBALS.MAKE_CONFIG.directory))
				)):
					changed_files.append(FileSource(source_path, destination_path, language))
				files.append(FileSource(source_path, destination_path, language))

	if PROPERTIES.get_value("debug"):
		debug(f"Files ({len(files)}): {', '.join([str(file) for file in files])}")
		debug(f"Changed Files ({len(changed_files)}): {', '.join([str(file) for file in changed_files])}")
		debug(f"Directories ({len(directories)}): {', '.join([str(directory) for directory in directories])}")
		debug(f"Changed Directories ({len(changed_directories)}): {', '.join([str(directory) for directory in changed_directories])}")

	return changed_files, files, changed_directories, directories

def copy_build_targets(files: List[FileSource], directories: List[DirectorySource]) -> None:
	temporary_directory = GLOBALS.MAKE_CONFIG.get_build_path("sources")

	for source in directories:
		temporary_script = join(temporary_directory, basename(source.destination_path))

		if not isfile(temporary_script) or GLOBALS.BUILD_STORAGE.is_path_changed(temporary_script) or not isfile(source.destination_path):
			if isfile(temporary_script):
				copy_file(temporary_script, source.destination_path)
			else:
				attention(f"Not found build target {basename(temporary_script)!r}, maybe it building emitted error or corresponding source is empty.")
				continue

		if not GLOBALS.BUILD_STORAGE.is_path_changed(temporary_script):
			frozen(f"Build target {basename(temporary_script)!r} is not changed.")

	for source in files:
		# Single JavaScript sources when TypeScript is not forced just copies to output without
		# temporary caching; might be breaking change in future.
		if GLOBALS.TSC_COMPOSITE.requires_composite() and source.language != "javascript":
			temporary_script = join(temporary_directory, relpath(source.source_path, GLOBALS.MAKE_CONFIG.directory))
		else:
			temporary_script = source.source_path

		if temporary_script == source.source_path and isfile(temporary_script) and GLOBALS.BUILD_STORAGE.is_path_changed(temporary_script):
			print(f"Flushing {basename(source.destination_path)!r} from {basename(source.source_path)!r}")

		if not isfile(temporary_script) or GLOBALS.BUILD_STORAGE.is_path_changed(temporary_script) or not isfile(source.destination_path):
			if isfile(temporary_script):
				copy_file(temporary_script, source.destination_path)
			else:
				attention(f"Not found build target {basename(temporary_script)!r}, but it directly included!")
				continue

		if not GLOBALS.BUILD_STORAGE.is_path_changed(temporary_script):
			frozen(f"Build target {basename(temporary_script)!r} is not changed.")

	GLOBALS.BUILD_STORAGE.save()

def request_type_check() -> int:
	type_check_mode = GLOBALS.PREFERRED_CONFIG.get_value("typeChecking", "always")
	should_type_check = (
		type_check_mode == "always"
		or (type_check_mode == "on-release" and PROPERTIES.get_value("release"))
	)

	if should_type_check:
		debug("Running type-check via tsc --noEmit")
		startup_millis = time()
		overall_result = GLOBALS.TSC_COMPOSITE.type_check(*(
			["--force"] if PROPERTIES.get_value("release") else []
		))
		startup_millis = time() - startup_millis

		if overall_result != 0:
			failure(f"Type-check failed in {startup_millis:.2f}s with result {overall_result}.")
			return overall_result
		success(f"Type-check completed in {startup_millis:.2f}s.")
	return 0

def build_composite_project() -> int:
	changed_files, files, changed_directories, directories = compute_and_capture_changed_scripts()

	from .script_setup import should_use_babel
	use_babel = should_use_babel()
	tsc_available = request_typescript(only_check=True)

	overall_result = 0
	if tsc_available:
		for source in files:
			if source.language == "typescript":
				GLOBALS.TSC_COMPOSITE.coerce(source.source_path)
		for source in directories:
			if source.language == "typescript":
				GLOBALS.TSC_COMPOSITE.reference(source.includes.directory)
		GLOBALS.TSC_COMPOSITE.flush()

		if use_babel:
			overall_result += request_type_check()
			if overall_result != 0:
				return overall_result

	for source in changed_directories:
		if source.language == "javascript":
			overall_result += source.includes.build(source.destination_path, source.language)
	if overall_result != 0:
		return overall_result

	if tsc_available and GLOBALS.TSC_COMPOSITE.has_sources():
		detected_changes = list(filter(lambda source: source.language == "typescript", chain(changed_files, changed_directories)))

		# Recomputed changes doesn't really matter for tsc, since we'll just want to realize
		# which files changed with hashing algorithm and composite building may rebuild everything
		# when tsconfig changes or something unexpected happened, like removing temporary declarations
		if len(detected_changes) > 0:
			debug("Rebuilding composite", ", ".join([
				basename(source.destination_path) for source in detected_changes
			]))

			from time import time
			startup_millis = time()

			if use_babel:
				from .babel_build import transpile_with_babel
				from .babel_setup import generate_toolchain_babel_config
				for source in detected_changes:
					babel_config_path = join(
						GLOBALS.MAKE_CONFIG.get_build_path("sources"),
						".toolchain.babel.config.json"
					)
					generate_toolchain_babel_config(babel_config_path)

					source_path = source.source_path if isinstance(source, FileSource) else source.includes.directory
					overall_result += transpile_with_babel(
						ordered_files=[source_path],
						output_path=source.destination_path,
						babel_config_path=babel_config_path,
						source_directory=GLOBALS.MAKE_CONFIG.directory,
						force=bool(PROPERTIES.get_value("release")),
					)
			else:
				overall_result += GLOBALS.TSC_COMPOSITE.build(*( 
					["--force"] if PROPERTIES.get_value("release") else []
				))

			startup_millis = time() - startup_millis
			if overall_result == 0:
				success(f"Completed composite script rebuild in {startup_millis:.2f}s!")
			else:
				failure(f"Failed composite script rebuild in {startup_millis:.2f}s with result {overall_result}.")

		if overall_result != 0:
			return overall_result

	copy_build_targets(files, directories)
	GLOBALS.PROJECT_STRUCTURE.generate_config()
	return overall_result
