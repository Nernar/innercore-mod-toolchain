from .context import GLOBALS, PROPERTIES
from os.path import basename, exists, isdir, isfile, join, relpath
from typing import Any, List, MutableMapping, Tuple

pass
from .includes import Includes
from .language import MakeScriptData
from .output_directory import expand_paths
from .logger import attention, failure, frozen, debug, print, success
from .utils import (RuntimeCodeError, copy_file, ensure_not_whitespace,
                    walk_all_files)
from .script_setup import request_typescript


def build_all_scripts(watch: bool = False) -> int:
	GLOBALS.PROJECT_STRUCTURE.cleanup_target("scripts")
	GLOBALS.PROJECT_STRUCTURE.cleanup_target("libraries")

	if request_typescript(only_check=True) and not isdir(GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("declarations")):
		from .output_directory import get_config_directory
		if not isdir(join(get_config_directory(), "declarations")):
			attention("Not found 'declarations', in most cases build will be failed, please install it via tasks.")

	return build_composite_project() if not watch else watch_composite_project()

def rebuild_build_target(source: MakeScriptData, target_path: str) -> str:
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

	target_type = "script_library" if source.type == "library" else "script_source"
	return GLOBALS.PROJECT_STRUCTURE.declare_target(
		keyword=target_type,
		relative_path=target_path,
		declare=declare
	).absolute_path

def compute_and_capture_changed_scripts() -> Tuple[List[Tuple[str, str, str]], List[Tuple[str, str, str]], List[Tuple[Includes, str, str]], List[Tuple[str, str]]]:
	composite = list()
	computed_composite = list()
	includes = list()
	computed_includes = list()

	for source in GLOBALS.MAKE_CONFIG.iterate_scripts():
		includes_path = ensure_not_whitespace(source.includes_path, ".includes")

		for source_path in expand_paths(GLOBALS.MAKE_CONFIG.get_relative_path(source.relative_path)):
			if not exists(source_path):
				attention(f"Skipped non-existing source {GLOBALS.MAKE_CONFIG.get_path_to_config(source_path)!r}!")
				continue

			# Supports assembling directories, JavaScript and TypeScript
			preffered_typescript = False
			if not isdir(source_path):
				preffered_typescript = source_path.endswith(".ts")
				if not preffered_typescript and not source_path.endswith(".js"):
					attention(f"Unsupported script {GLOBALS.MAKE_CONFIG.get_path_to_config(source_path)!r}, it should be directory with includes or Java/TypeScript file!")
					continue
			else:
				try:
					def walk(file: str) -> None:
						if file.endswith(".ts") and not file.endswith(".d.ts"):
							raise RuntimeError()
					walk_all_files(source_path, walk)
				except RuntimeError:
					preffered_typescript = True

			language = ensure_not_whitespace(source.language, "typescript" if preffered_typescript else "javascript")
			if language == "typescript" and not request_typescript():
				if preffered_typescript:
					raise RuntimeCodeError(255, f"We cannot compile source {GLOBALS.MAKE_CONFIG.get_path_to_config(source_path)!r} without you having Node.js, despite `denyTypeScript` property of your 'toolchain.json' being active. Please disable it and install Node.js to compile TypeScript sources.")
				attention(f"Source {GLOBALS.MAKE_CONFIG.get_path_to_config(source_path)!r} specifies target language as TypeScript, so this script probably uses ESNext capabilities. Build as normal JavaScript files, since `denyTypeScript` property of your 'toolchain.json' is active.")
				language = "javascript"

			# Preserve output target duplication
			target_path = source.output_path
			try:
				dot_index = target_path.rindex(".")
				target_path = target_path[:dot_index] + "{}" + target_path[dot_index:]
			except ValueError:
				target_path += "{}"

			destination_path = rebuild_build_target(source, target_path)
			appending_library = GLOBALS.MAKE_CONFIG.get_value("project.compiledLibraries", False) \
				and source.type == "library" and source.language == "javascript"

			if isdir(source_path):
				include = Includes.invalidate(source_path, includes_path)
				# Computing in any case, tsconfig normalises environment usage
				if include.compute(destination_path, "typescript" if not appending_library else "javascript"):
					includes.append((
						include,
						destination_path,
						"javascript" if appending_library else language
					))
				if not appending_library and GLOBALS.MAKE_CONFIG.get_value("project.useReferences", False) and language == "typescript":
					GLOBALS.TSC_COMPOSITE.reference(source_path)
				computed_includes.append((
					source_path, destination_path
				))

			elif isfile(source_path):
				if not appending_library:
					if GLOBALS.MAKE_CONFIG.get_value("project.composite", True) and language == "typescript":
						GLOBALS.TSC_COMPOSITE.coerce(source_path)
					if GLOBALS.BUILD_STORAGE.is_path_changed(source_path) or (
						language == "typescript" and not isfile(
							join(GLOBALS.MAKE_CONFIG.get_build_path("sources"), relpath(source_path, GLOBALS.MAKE_CONFIG.directory))
						)
					):
						composite.append((source_path, destination_path, language))
				computed_composite.append((
					source_path, destination_path, "javascript" if appending_library else language
				))

	return composite, computed_composite, includes, computed_includes

def copy_build_targets(composite: List[Tuple[str, str, str]], includes: List[Tuple[str, str]]) -> None:
	temporary_directory = GLOBALS.MAKE_CONFIG.get_build_path("sources")

	for included in includes:
		temporary_script = join(temporary_directory, basename(included[1]))

		if not isfile(temporary_script) or GLOBALS.BUILD_STORAGE.is_path_changed(temporary_script) or not isfile(included[1]):
			if isfile(temporary_script):
				copy_file(temporary_script, included[1])
			else:
				attention(f"Not found build target {basename(temporary_script)!r}, maybe it building emitted error or corresponding source is empty.")
				continue

		if not GLOBALS.BUILD_STORAGE.is_path_changed(temporary_script):
			frozen(f"Build target {basename(temporary_script)!r} is not changed.")

	for included in composite:
		# Single JavaScript sources when TypeScript is not forced just copies to output without
		# temporary caching; might be breaking change in future.
		if GLOBALS.MAKE_CONFIG.get_value("project.composite", True) and included[2] != "javascript":
			temporary_script = join(temporary_directory, relpath(included[0], GLOBALS.MAKE_CONFIG.directory))
		else:
			temporary_script = included[0]

		if temporary_script == included[0] and isfile(temporary_script) and GLOBALS.BUILD_STORAGE.is_path_changed(temporary_script):
			print(f"Flushing {basename(included[1])!r} from {basename(included[0])!r}")

		if not isfile(temporary_script) or GLOBALS.BUILD_STORAGE.is_path_changed(temporary_script) or not isfile(included[1]):
			if isfile(temporary_script):
				copy_file(temporary_script, included[1])
			else:
				attention(f"Not found build target {basename(temporary_script)!r}, but it directly included!")
				continue

		if not GLOBALS.BUILD_STORAGE.is_path_changed(temporary_script):
			frozen(f"Build target {basename(temporary_script)!r} is not changed.")

	GLOBALS.BUILD_STORAGE.save()

def build_composite_project() -> int:
	overall_result = 0

	composite, computed_composite, includes, computed_includes = compute_and_capture_changed_scripts()

	if request_typescript(only_check=True):
		GLOBALS.TSC_COMPOSITE.flush()
	for included in includes:
		if not GLOBALS.MAKE_CONFIG.get_value("project.useReferences", False) or included[2] == "javascript":
			overall_result += included[0].build(included[1], included[2])
	if overall_result != 0:
		return overall_result

	if request_typescript(only_check=True) \
		and (GLOBALS.MAKE_CONFIG.get_value("project.composite", True) \
			or GLOBALS.MAKE_CONFIG.get_value("project.useReferences", False)):

		which = list()
		if GLOBALS.MAKE_CONFIG.get_value("project.composite", True):
			which += list(filter(lambda included: included[2] == "typescript", composite))

		no_composite_typescript = len(which) == 0
		if GLOBALS.MAKE_CONFIG.get_value("project.useReferences", False):
			which += list(filter(lambda included: included[2] == "typescript", includes))

		# Quick rebuild means running tsc only on changed directory, which is must be faster
		# than default composite building; but in some cases it also may cause unexpected behavior
		if no_composite_typescript and len(which) == 1 and GLOBALS.MAKE_CONFIG.get_value("project.quickRebuild", True):
			included = which.pop()
			overall_result += included[0].build(included[1], included[2])

		# Recomputed changes doesn't really matter for tsc, since we'll just want to realize
		# which files changed with hashing algorithm and composite building may rebuild everything
		# when tsconfig changes or something unexpected happened, like removing temporary declarations
		if len(which) > 0:
			debug("Rebuilding composite", ", ".join([
				basename(included[1]) for included in which
			]))

			from time import time
			startup_millis = time()
			overall_result += GLOBALS.TSC_COMPOSITE.build(*(
				["--force"] if PROPERTIES.get_value("release") else list()
			))

			startup_millis = time() - startup_millis
			if overall_result == 0:
				success(f"Completed composite script rebuild in {startup_millis:.2f}s!")
			else:
				failure(f"Failed composite script rebuild in {startup_millis:.2f}s with result {overall_result}.")

		if overall_result != 0:
			return overall_result

	copy_build_targets(computed_composite, computed_includes)
	GLOBALS.PROJECT_STRUCTURE.generate_config()
	return overall_result

def watch_composite_project() -> int:
	if not request_typescript():
		failure("Watching is not supported for legacy JavaScript!")
		return 1
	overall_result = 0

	# Recomputing existing changes before watching, changes here doesn't make sence
	# since it will be recomputed after watching interruption
	compute_and_capture_changed_scripts()
	GLOBALS.TSC_COMPOSITE.flush()
	GLOBALS.TSC_COMPOSITE.watch()
	GLOBALS.PROJECT_STRUCTURE.cleanup_target("scripts")
	GLOBALS.PROJECT_STRUCTURE.cleanup_target("libraries")
	GLOBALS.TSC_COMPOSITE.reset()

	composite, computed_composite, includes, computed_includes = compute_and_capture_changed_scripts()

	for included in includes:
		if not GLOBALS.MAKE_CONFIG.get_value("project.useReferences", False) or included[2] == "javascript":
			overall_result += included[0].build(included[1], included[2])
	if overall_result != 0:
		return overall_result

	copy_build_targets(computed_composite, computed_includes)
	GLOBALS.PROJECT_STRUCTURE.generate_config()
	return overall_result
