import os
import subprocess
from itertools import tee
from os.path import abspath, basename, exists, isdir, isfile, join, relpath
from typing import (Collection, Iterable, List, MutableSequence, NamedTuple,
                    Optional)

from . import GLOBALS, PROPERTIES
from .config import Config, FileConfig
from .language import MakeNativeData
from .native_setup import arch_to_abi, prepare_compiler_executable
from .output_directory import expand_paths
from .shell import debug, error, info, pretty_print, warn
from .utils import (copy_directory, copy_file, ensure_directory, ensure_file,
                    ensure_file_directory, ensure_not_whitespace,
                    get_all_files, remove_tree)

CODE_OK = 0
CODE_FAILED_NO_GCC = 1001
CODE_FAILED_INVALID_MANIFEST = 1002
CODE_DUPLICATE_NAME = 1003
CODE_INVALID_JSON = 1004
CODE_INVALID_PATH = 1005


class BuildTarget(NamedTuple):
	directory: str
	relative_directory: str
	output_directory: str
	manifest: MakeNativeData
	stdincludes: MutableSequence[str]

def collect_stdincludes_directories(directories: Optional[Collection[str]]) -> List[str]:
	stdincludes = list()
	if not directories:
		return stdincludes
	for directory in directories:
		stdincludes_directory = GLOBALS.MAKE_CONFIG.get_path(directory)
		if not isdir(stdincludes_directory):
			stdincludes_directory = GLOBALS.TOOLCHAIN_CONFIG.get_path(directory)
		if not isdir(stdincludes_directory):
			warn(f"* Skipped non-existing stdincludes directory {directory!r}, please make sure that them exist!")
			continue
		has_directories = False
		for filename in os.listdir(stdincludes_directory):
			stdincludes_headers = join(stdincludes_directory, filename)
			if isdir(stdincludes_headers):
				stdincludes.append(stdincludes_headers)
				has_directories = True
			elif not has_directories and filename.endswith((".h", ".hpp")):
				warn(f"* Header {filename} should be inside any of stdincludes directory, otherwise it will be ignored.")
	return stdincludes

def get_manifest(directory: str) -> FileConfig:
	return FileConfig(join(directory, "manifest"))

def get_name_from_manifest(directory: str) -> Optional[str]:
	try:
		return get_manifest(directory).get_value("shared.name", lambda: basename(directory))
	except:
		return None

def search_in_directory(parent: str, name: str) -> Optional[str]:
	for dirpath, dirnames, filenames in os.walk(parent):
		for relative_directory in dirnames:
			path = join(dirpath, relative_directory)
			if get_name_from_manifest(path) == name:
				return path

def get_fake_so_directory(abi: str) -> str:
	fake_so_directory = GLOBALS.TOOLCHAIN_CONFIG.get_relative_path(join("ndk", "fakeso", abi))
	ensure_directory(fake_so_directory)
	return fake_so_directory

def add_fake_so(executable: str, abi: str, name: str) -> None:
	file = join(get_fake_so_directory(abi), "lib" + name + ".so")
	if not isfile(file):
		result = subprocess.call([
			executable, "-std=c++11",
			GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("bin/fakeso.cpp"),
			"-shared", "-o", file
		])
		if result == 0:
			debug(f"Created linking fake so {name!r} successfully")
		else:
			warn(f"Stubbing fake so failed with result {result}!")

RUNTIME_ARCHES = {
	"arm64-v8a": "aarch64",
	"x86_64": "x86-64"
}

def abi_to_runtime_architecture(abi: str) -> str:
	if abi in RUNTIME_ARCHES:
		return RUNTIME_ARCHES[abi]
	return abi

def is_relevant_configuration(configuration: str, *properties: str) -> bool:
	if len(configuration) == 0 or configuration == "*":
		return True
	rules = configuration.split("-")
	rule_match_abi = None
	for rule in rules:
		try:
			arch = arch_to_abi(rule)
			if arch in properties:
				rule_match_abi = True
			elif rule_match_abi is None:
				rule_match_abi = False
			continue
		except ValueError:
			pass
		if rule == "debug" or rule == "release":
			is_release = PROPERTIES.get_value("release")
			if (is_release and rule == "debug") or (not is_release and rule == "release"):
				return False
			continue
		if rule in properties:
			continue
		# debug(f"* Mismatched rule {rule} in configuration {configuration!r}, ignoring it...")
		return False
	return rule_match_abi != False

def merge_relevant_configurations(configurations: Config, *properties: str) -> Config:
	relevant = Config()
	for key, config in configurations.items():
		if isinstance(config, Config) and is_relevant_configuration(key, *properties):
			relevant.merge_config(config)
	return relevant

def get_native_build_targets(directories: Iterable[MakeNativeData]) -> List[BuildTarget]:
	targets = list()

	for native_data in directories:
		directory = GLOBALS.MAKE_CONFIG.get_path(native_data.relative_path)
		output_directory = GLOBALS.MOD_STRUCTURE.new_build_target("native", native_data.output_path)
		ensure_directory(output_directory)
		stdincludes = collect_stdincludes_directories(list(native_data.stdincludes))
		target = BuildTarget(directory, native_data.output_path, output_directory, native_data, stdincludes)
		targets.append(target)

	return targets

def compile_directory_with_gcc(directory: str, target_directory: str, target_so: str, abi: str, stdincludes: Collection[str], manifest: MakeNativeData) -> int:
	info(f"* Compiling {manifest.shared_name!r} for {abi}")
	soname = f"lib{manifest.shared_name}.so"

	options = list(manifest.options)
	if not options or len(options) == 0:
		options = ["-std=c++11"]
	debug(", ".join(options))

	executable = prepare_compiler_executable(abi)
	compiler_command = [executable, "-DANDROID_STL=c++_static"]
	includes = list()
	for stdincludes_directory in reversed(list(stdincludes)):
		includes.append(f"-I{stdincludes_directory}")
	dependencies = [f"-L{get_fake_so_directory(abi)}", "-landroid", "-lm", "-llog", "-ldl", "-lc"]
	links = list(manifest.link)
	if not "horizon" in links:
		links.append("horizon")
	for link in links:
		add_fake_so(executable, abi, link)
		dependencies.append(f"-l{link}")

	# Always search for dependencies in current directory.
	search_directory = abspath(join(directory, ".."))
	for dependency in manifest.depends:
		if dependency:
			add_fake_so(executable, abi, dependency)
			dependencies.append("-l" + dependency)
			dependency_directory = search_in_directory(search_directory, dependency)
			if dependency_directory:
				try:
					for include_directory in get_manifest(dependency_directory).obtain_list("shared.include"):
						includes.append("-I" + join(dependency_directory, include_directory))
				except KeyError:
					pass
		else:
			warn(f"* Dependency directory {dependency} is not found, it will be skipped.")
	for include in manifest.include:
		includes.append("-I" + join(directory, include))

	# Collect files and prepare output cache directories.
	source_files = get_all_files(directory, extensions=(".cpp", ".c"))
	preprocessed_directory = abspath(join(target_directory, "preprocessed", abi))
	ensure_directory(preprocessed_directory)
	object_directory = abspath(join(target_directory, "object", abi))
	ensure_directory(object_directory)

	# Preprocess to compile changed sources.
	import filecmp
	object_files = list()
	object_position = 1
	recompiled_count = 0
	total_count = len(source_files)

	for file in source_files:
		relative_file = relpath(file, directory)
		debug(f"Preprocessing {relative_file} ({object_position}/{total_count}){' ' * 48}", end="\r")

		object_file = join(object_directory, relative_file) + ".o"
		preprocessed_file = join(preprocessed_directory, relative_file)
		tmp_preprocessed_file = preprocessed_file + ".tmp"
		ensure_file_directory(preprocessed_file)
		ensure_file_directory(object_file)
		object_files.append(object_file)

		result = subprocess.call(compiler_command + [
			"-E", file, "-o", tmp_preprocessed_file
		] + includes + options)

		if result == CODE_OK:
			if not isfile(preprocessed_file) or not isfile(object_file) \
					or not filecmp.cmp(preprocessed_file, tmp_preprocessed_file):
				if isfile(preprocessed_file):
					os.remove(preprocessed_file)
				os.rename(tmp_preprocessed_file, preprocessed_file)
				if isfile(object_file):
					os.remove(object_file)

				debug(f"Compiling {relative_file} ({object_position}/{total_count}){' ' * 48}", end="\r")
				result = max(result, subprocess.call(compiler_command + [
					"-c", preprocessed_file, "-o", object_file
				] + options + ([] if "64" in abi else ["-shared"])))
				if result != CODE_OK:
					if isfile(object_file):
						os.remove(object_file)
					overall_result = result
				else:
					recompiled_count += 1
		else:
			if isfile(object_file):
				os.remove(object_file)
			overall_result = result
		object_position += 1

	if overall_result != CODE_OK:
		pretty_print()
		return overall_result
	debug(f"Recompiled {recompiled_count}/{total_count} files with result {overall_result} ({'OK' if overall_result == 0 else 'ERROR'}){' ' * 48}")

	for link in manifest.link_static:
		link_path = GLOBALS.MAKE_CONFIG.get_relative_path(join("static_libs", abi, link))
		if isdir(link_path):
			for object_file in get_all_files(link_path):
				object_files.append(object_file)
		elif exists(link_path):
			object_files.append(link_path)
		else:
			warn(f"* Skipped static library {link}, because it was not exist.")

	debug("Linking object files")
	ensure_file(target_so)
	linking_command = list()
	linking_command += compiler_command
	modified_objects = join(object_directory, "modified_objects.rsp")
	with open(modified_objects, "w", encoding="utf-8") as modified:
		modified.writelines(path.replace("\\", "\\\\") + "\n" for path in object_files)
	linking_command.append("@" + modified_objects)
	make_path = join(directory, "make.txt")
	if isfile(make_path):
		with open(make_path, encoding="utf-8") as file:
			make = file.read()
		if ensure_not_whitespace(make):
			linking_command.append(make.rstrip())
	linking_command.append("-shared")
	linking_command.append("-Wl,-soname=" + soname)
	if "-flto" in options:
		debug("Linker time optimization is enabled")
		linking_command += options
	linking_command.append("-o")
	linking_command.append(target_so)
	linking_command += includes
	linking_command += dependencies
	return subprocess.call(linking_command)

def build_native_directories(directories: Iterable[MakeNativeData], directory_tuples: Iterable[tuple[str, Iterable[MakeNativeData]]], target_directory: str) -> int:
	targets = get_native_build_targets(directories)
	abi_targets = [(
		directory[0],
		iter(get_native_build_targets(directory[1]))
	) for directory in directory_tuples]

	for target in targets:
		target_library_directory = join(target_directory, target.relative_directory)
		soname = f"lib{target.manifest.shared_name}.so"

		if target.manifest.keep_sources:
			# Copy everything without built directories.
			copy_directory(target.directory, target.output_directory, clear_destination=True)
			remove_tree(join(target.output_directory, "so"))
			os.remove(join(target.output_directory, soname))
		else:
			# Cleanup built directories and copy manifest.
			remove_tree(target.output_directory)
			copy_file(join(target.directory, "manifest"), join(target.output_directory, "manifest"))

			# Also copy includes if necessary.
			keep_includes = target.manifest.keep_includes
			for include_path in target.manifest.include:
				output_include_path = join(target.output_directory, include_path)
				if keep_includes:
					src_include_path = join(target.directory, include_path)
					if isdir(src_include_path):
						copy_directory(src_include_path, output_include_path, clear_destination=True)
					else:
						warn(f"* Shared headers folder {include_path!r} does not exist, check your build configuration!")
				else:
					remove_tree(output_include_path)

		# Copy already prebuilt libraries, output path will be 'libname.so' or 'so/arch/libname.so'.
		if exists(join(target.directory, ".precompiled")):
			info(f"* Library directory {target.directory} skipped, because precompiled flag is set.")

			libraries_count = 0
			for abi, scoped_directories in abi_targets:
				source_library = abspath(join(target.directory, "so", abi, soname))
				if isfile(source_library):
					target_library = abspath(join(target.output_directory, "so", abi_to_runtime_architecture(abi), soname))
					copy_file(source_library, target_library)
					libraries_count += 1

			if libraries_count == 0:
				source_library = abspath(join(target.directory, soname))
				if isfile(source_library):
					target_library = abspath(join(target.output_directory, soname))
					copy_file(source_library, target_library)
					libraries_count += 1

			if libraries_count == 0:
				warn(f"* Library directory {target.directory} should be precompiled, but there is no shared libraries.")
				return CODE_FAILED_INVALID_MANIFEST
			continue

		# Compile library for requested ABIs.
		overall_result = CODE_OK
		for abi, scoped_directories in abi_targets:
			scoped_target = next(scoped_directories)
			target_so = abspath(join(target.output_directory, soname)) if len(abi_targets) == 1 \
				else abspath(join(target.output_directory, "so", abi_to_runtime_architecture(abi), soname))

			overall_result += compile_directory_with_gcc(
				scoped_target.directory,
				target_library_directory,
				target_so,
				abi,
				scoped_target.stdincludes,
				scoped_target.manifest
			)
			if overall_result != 0:
				return overall_result

	return CODE_OK

def compile_native(abis: Collection[str]) -> int:
	from time import time
	startup_millis = time()
	overall_result = CODE_OK
	target_directory = GLOBALS.MAKE_CONFIG.get_build_path("gcc")
	ensure_directory(target_directory)
	GLOBALS.MOD_STRUCTURE.cleanup_build_target("native")

	stdincludes_directories = list()
	stdincludes_toolchain = GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("stdincludes")
	if isdir(stdincludes_toolchain):
		stdincludes_directories.append(stdincludes_toolchain)
	stdincludes_custom = GLOBALS.MAKE_CONFIG.get_relative_path("stdincludes")
	if exists(stdincludes_custom):
		stdincludes_directories.append(stdincludes_custom)
	if not isdir(stdincludes_toolchain):
		warn("Not found 'stdincludes', in most cases build will be failed, please install it via tasks.")

	# Apply global configurations to preserve keepIncludes, etc. in builds.
	optional_config = GLOBALS.MAKE_CONFIG.get_value("configurations")
	defaults = None
	if isinstance(optional_config, Config):
		defaults = merge_relevant_configurations(optional_config)

	toolchain_config = None
	if any(stdincludes_directories):
		toolchain_config = Config()
		toolchain_config.set_value("stdincludes", stdincludes_directories)
	if toolchain_config and defaults:
		defaults.merge_config(toolchain_config, exclusive_lists=True, extend_lists=True)

	directories = GLOBALS.MAKE_CONFIG.iterate_native(defaults=defaults)
	directories, has_anything = tee(directories)
	try:
		next(has_anything)
	except StopIteration:
		GLOBALS.MOD_STRUCTURE.update_build_config_list("nativeDirs")
		return 0

	directory_tuples: Iterable[tuple[str, Iterable[MakeNativeData]]] = []
	for abi in abis:
		optional_defaults = None
		if isinstance(optional_config, Config):
			optional_defaults = merge_relevant_configurations(optional_config, abi)
			if toolchain_config:
				optional_defaults.merge_config(toolchain_config, exclusive_lists=True, extend_lists=True)
		scoped_directories = GLOBALS.MAKE_CONFIG.iterate_native(defaults=optional_defaults)
		directory_tuples.append((abi, scoped_directories))

	overall_result = build_native_directories(directories, directory_tuples, target_directory)

	GLOBALS.MOD_STRUCTURE.update_build_config_list("nativeDirs")
	startup_millis = time() - startup_millis
	if overall_result == CODE_OK:
		pretty_print(f"Completed native build in {startup_millis:.2f}s!")
	else:
		error(f"Failed native build in {startup_millis:.2f}s with result {overall_result}.")

	return overall_result

def copy_shared_objects(abis: Collection[str]) -> int:
	shared_objects = GLOBALS.MAKE_CONFIG.iterate_shared_objects()
	shared_objects, has_anything = tee(shared_objects)
	try:
		next(has_anything)
	except StopIteration:
		return 0
	GLOBALS.MOD_STRUCTURE.cleanup_build_target("shared_object")
	order = set()

	debug(f"Copying shared objects")
	overall_result = 0
	for shared_object in shared_objects:
		relative_path = shared_object.relative_path
		for abi in abis:
			formatted_relative_path = relative_path.format(abi)
			for shared_object_path in expand_paths(GLOBALS.MAKE_CONFIG.get_relative_path(formatted_relative_path)):
				shared_object_name = basename(shared_object_path)
				if shared_object_name in order:
					warn(f"* Found duplicate shared object {formatted_relative_path}, overriding existing one...")
				output_relative_file = join(abi_to_runtime_architecture(abi), shared_object_name)
				output_file = GLOBALS.MOD_STRUCTURE.new_build_target("shared_object", output_relative_file)
				copy_file(shared_object_path, output_file)
				order.add(shared_object_name)

	if any(order):
		output_directory = GLOBALS.MOD_STRUCTURE.get_target_output_directory("shared_object")
		with open(join(output_directory, "order.txt"), "w", encoding="utf-8") as order_file:
			for shared_object in order:
				order_file.write(shared_object + "\n")

	if overall_result == 0:
		pretty_print(f"Completed including shared objects!")
	else:
		error(f"Failed to include shared objects with result {overall_result}.")
	return overall_result
