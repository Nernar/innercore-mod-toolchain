import json
import os
import platform
import re
import subprocess
from itertools import tee
from os.path import basename, exists, isdir, isfile, join, relpath, splitext
from typing import (Collection, Dict, Iterable, List, MutableSequence,
                    NamedTuple)
from zipfile import ZipFile

from . import GLOBALS, PROPERTIES
from .config import Config
from .language import PROJECT_TYPE_PACK, MakeJavaData
from .output_directory import expand_paths
from .shell import (abort, attention, failure, frozen, pretty_debug,
                    pretty_error, pretty_info, pretty_print, success)
from .utils import (copy_directory, copy_file, ensure_directory, ensure_file,
                    get_all_files, get_next_filename, remove_tree,
                    request_executable_version, request_tool, walk_all_files)


class BuildTarget(NamedTuple):
	directory: str
	relative_directory: str
	output_directory: str
	manifest: MakeJavaData
	classpath: MutableSequence[str]

TOOLCHAIN_CLASSPATH = None

def collect_classpath_files(directories: Collection[str]) -> List[str]:
	classpath = list()
	for directory in directories:
		classpath_directory = GLOBALS.MAKE_CONFIG.get_path(directory)
		if not isdir(classpath_directory):
			classpath_directory = GLOBALS.TOOLCHAIN_CONFIG.get_path(directory)
			if not isdir(classpath_directory):
				from .output_directory import get_config_directory
				classpath_directory = join(get_config_directory(), directory)
		if not isdir(classpath_directory):
			attention(f"Skipped non-existing classpath directory {directory!r}, please make sure that it exist!")
			continue
		libraries = get_all_files(classpath_directory, (".jar"))
		classpath.extend(libraries)
	global TOOLCHAIN_CLASSPATH
	if not TOOLCHAIN_CLASSPATH:
		from .output_directory import get_config_directory
		classpath_directory = join(get_config_directory(), "classpath")
		if isdir(classpath_directory):
			TOOLCHAIN_CLASSPATH = get_all_files(classpath_directory, (".jar"))
			if GLOBALS.MAKE_CONFIG.project_type == PROJECT_TYPE_PACK:
				innercore_test = join(classpath_directory, "innercore-test.jar")
				try:
					TOOLCHAIN_CLASSPATH.remove(innercore_test)
				except ValueError:
					attention("Failed to exclude 'innercore-test.jar' from classpath for package build, contact developer and tell them they are a arsehole.")
	if TOOLCHAIN_CLASSPATH:
		classpath.extend(TOOLCHAIN_CLASSPATH)
	return classpath

def flatten_classpath_files(targets: Collection[BuildTarget]) -> List[str]:
	return [
		library for target in targets for library in target.classpath
	]

def rebuild_library_cache(relative_directory: str, libraries: Collection[str], target_directory: str) -> List[str]:
	target_classes_directory = join(target_directory, "libraries", "classes", relative_directory)
	compressed_libraries = join(target_directory, "libraries", relative_directory + ".zip")

	pretty_debug(f"Rebuilding library cache: {relative_directory}")
	remove_tree(target_classes_directory)
	ensure_directory(target_classes_directory)

	import shutil
	for filename in libraries:
		pretty_debug(f"Extracting library classes: {basename(filename)}")
		shutil.unpack_archive(filename, target_classes_directory, "zip")

	pretty_debug("Zipping extracted cache")
	remove_tree(compressed_libraries)
	shutil.make_archive(compressed_libraries[:-4], "zip", target_classes_directory)
	return [compressed_libraries]

def update_modified_targets(targets: Collection[BuildTarget], target_directory: str) -> Dict[str, Dict[str, List[str]]]:
	modified_files = dict()

	for target in targets:
		classes_directory = join(target_directory, "classes", target.relative_directory, "classes")
		classes = GLOBALS.BUILD_STORAGE.get_modified_files(classes_directory, (".class")) if isdir(classes_directory) else []
		libraries = list()

		for library_path in target.manifest.libraries:
			library_directory = join(target.directory, library_path)
			if exists(library_directory) and isdir(library_directory):
				libraries.extend(GLOBALS.BUILD_STORAGE.get_modified_files(library_directory, (".jar")))
			else:
				attention(f"Directory {library_path!r} could not be found, please check your 'manifest' file!")

		if len(libraries) > 0:
			libraries = rebuild_library_cache(target.relative_directory, libraries, target_directory)
		if len(classes) > 0 or len(libraries) > 0:
			modified_files[target.relative_directory] = {
				"classes": classes,
				"libraries": libraries
			}

	return modified_files

def copy_additional_sources(targets: Collection[BuildTarget]) -> None:
	for target in targets:
		if target.manifest.keep_libraries:
			for relative_directory in target.manifest.libraries:
				directory = join(target.directory, relative_directory)
				if isdir(directory):
					copy_directory(directory, join(target.output_directory, relative_directory), clear_destination=True)

		if target.manifest.keep_sources:
			for relative_directory in target.manifest.sources:
				directory = join(target.directory, relative_directory)
				if isdir(directory):
					copy_directory(directory, join(target.output_directory, relative_directory), clear_destination=True)

		manifest_json = {
			"source-dirs": list(target.manifest.sources),
			"library-dirs": list(target.manifest.libraries)
		}
		with open(join(target.output_directory, "manifest"), "w", encoding="utf-8") as manifest:
			manifest.write(json.dumps(manifest_json, ensure_ascii=False))
			manifest.write("\n")

### D8/L8/R8

def run_d8(target: BuildTarget, modified_pathes: Dict[str, List[str]], classpath: Collection[str], target_directory: str) -> int:
	java_executable = request_tool("java")
	if not java_executable:
		abort("Executable 'java' is required for compilation, nothing to do.")

	classpath_targets = list()
	for filename in classpath:
		classpath_targets += ["--classpath", filename]
	compressed_libraries = join(target_directory, "classes", target.relative_directory, "libs", target.relative_directory + "-all.jar")
	libraries = list()
	if exists(compressed_libraries):
		libraries += ["--lib", compressed_libraries]
	else:
		walk_all_files((join(target.directory, library) for library in target.manifest.libraries), lambda filename: libraries.extend(("--lib", filename)), (".jar"))

	target_d8_directory = join(target_directory, "d8", target.relative_directory)
	compressed_target = target_d8_directory + ".zip"
	ensure_directory(target_d8_directory)

	modified_class_pathes = modified_pathes["classes"]
	modified_classes = join(target_d8_directory, "modified_classes.rsp")
	with open(modified_classes, "w", encoding="utf-8") as modified:
		modified.writelines(path + "\n" for path in modified_class_pathes)
	modified_library_pathes = modified_pathes["libraries"]
	modified_libraries = join(target_d8_directory, "modified_libraries.rsp")
	with open(modified_libraries, "w", encoding="utf-8") as modified:
		modified.writelines(path + "\n" for path in modified_library_pathes)

	from .output_directory import get_config_directory
	r8_executable = join(get_config_directory(), "r8", "r8.jar")

	pretty_debug("Dexing libraries")
	result = subprocess.run([
		java_executable,
		"-classpath", r8_executable,
		"com.android.tools.r8.D8",
		f"@{modified_libraries}"
	] + classpath_targets + libraries + [
		"--min-api", "19",
		"--release" if PROPERTIES.get_value("release") else "--debug",
		"--intermediate",
		"--output", target_d8_directory
	], text=True, capture_output=True)
	if result.returncode != 0:
		pretty_error(result.stderr.strip())
		return result.returncode

	pretty_debug("Dexing classes")
	result = subprocess.run([
		java_executable,
		"-classpath", r8_executable,
		"com.android.tools.r8.D8",
		f"@{modified_classes}"
	] + classpath_targets + libraries + [
		"--min-api", "19",
		"--release" if PROPERTIES.get_value("release") else "--debug",
		"--intermediate",
		"--file-per-class",
		"--output", target_d8_directory
	], text=True, capture_output=True)
	if result.returncode != 0:
		pretty_error(result.stderr.strip())
		return result.returncode

	pretty_debug("Compressing archives")
	with ZipFile(compressed_target, "w") as archive:
		walk_all_files(target_d8_directory, lambda filename: archive.write(filename, arcname=filename[len(target_d8_directory) + 1:]), (".dex"))

	return 0

def merge_compressed_dexes(target: BuildTarget, target_directory: str) -> int:
	compressed_target = join(target_directory, "d8", target.relative_directory + ".zip")
	output_directory = join(target_directory, "odex", target.relative_directory)
	remove_tree(output_directory)
	ensure_directory(output_directory)

	java_executable = request_tool("java")
	if not java_executable:
		abort("Executable 'java' is required for compilation, nothing to do.")
	from .output_directory import get_config_directory
	r8_executable = join(get_config_directory(), "r8", "r8.jar")

	pretty_debug("Merging dex")
	result = subprocess.run([
		java_executable,
		"-classpath", r8_executable,
		"com.android.tools.r8.D8",
		compressed_target,
		"--min-api", "19",
		"--release" if PROPERTIES.get_value("release") else "--debug",
		"--intermediate",
		"--output", output_directory
	], text=True, capture_output=True)
	if result.returncode != 0:
		pretty_error(result.stderr.strip())
		return result.returncode

	return 0

### JAVAC

def build_java_with_javac(targets: Collection[BuildTarget], target_directory: str) -> int:
	javac_executable = None
	supports_modules = False

	for target in targets:
		source_directories = list(target.manifest.sources)
		library_directories = list(target.manifest.libraries)
		if not any(source_directories) and not any(library_directories):
			continue

		from time import time
		startup_millis = time()
		target_compiler_directory = join(target_directory, "classes", target.relative_directory)
		target_classes_directory = join(target_compiler_directory, "classes")
		ensure_directory(target_classes_directory)
		target_sources_directory = join(target_compiler_directory, "generated", "sources", "annotationProcessor")
		target_headers_directory = join(target_compiler_directory, "generated", "sources", "headers")
		ensure_directory(target_sources_directory)
		ensure_directory(target_headers_directory)

		classes_listing = join(target_compiler_directory, ".classes")
		if not write_changed_source_files(target, source_directories, classes_listing):
			frozen(f"Directory {target.relative_directory!r} is not changed.")
			continue

		if not javac_executable:
			javac_executable = request_tool("javac")
			if not javac_executable:
				abort("Executable 'javac' is required for compilation, nothing to do.")
			supports_modules = request_executable_version(javac_executable)
			supports_modules = supports_modules >= 1.9 or supports_modules >= 9

		options = list(target.manifest.options)
		if supports_modules:
			options += ["--release", "8"]
		else:
			options += [
				"-source", "8",
				"-target", "8"
			]
		if target.manifest.verbose:
			options.append("-verbose")
		if len(source_directories) > 0:
			options += ["-sourcepath", os.pathsep.join(join(target.directory, source) for source in source_directories)]
		precompiled = list()
		if supports_modules:
			precompiled += target.classpath
		else:
			# Might be unstable with lambdas, desugaring requires JDK >= 9.
			options += ["-bootclasspath", os.pathsep.join(target.classpath)]
		if len(library_directories) > 0:
			precompiled += get_all_files((join(target.directory, library) for library in library_directories), (".jar"))
		options += ["-classpath", os.pathsep.join(precompiled)]

		result = subprocess.run([
			javac_executable
		] + options + [
			"-Xlint",
			"-Xlint:-cast",
			"-implicit:class",
			"-d", target_classes_directory,
			"-s", target_sources_directory,
			"-h", target_headers_directory,
			f"@{classes_listing}"
		], text=True, capture_output=True)
		startup_millis = time() - startup_millis
		if result.returncode != 0:
			pretty_error(result.stderr.strip())
			failure(f"Failed {target.relative_directory!r} compilation in {startup_millis:.2f}s with result {result.returncode}.")
			return result.returncode
		success(f"Completed {target.relative_directory!r} compilation in {startup_millis:.2f}s!")
	return 0

def write_changed_source_files(target: BuildTarget, directories: Collection[str], filename: str) -> bool:
	contains_modifications = False
	with open(filename, "w", encoding="utf-8") as output:
		for directory in directories:
			modifications = GLOBALS.BUILD_STORAGE.get_modified_files(join(target.directory, directory), (".java"))
			try:
				next(iter(modifications))
			except StopIteration:
				continue
			contains_modifications = True
			output.writelines(json.dumps(modification, ensure_ascii=False) + os.linesep for modification in modifications)
	return contains_modifications

### ECJ

def build_java_with_ecj(targets: Collection[BuildTarget], target_directory: str) -> int:
	ecj_executable = None

	for target in targets:
		source_directories = list(target.manifest.sources)
		library_directories = list(target.manifest.libraries)
		if not any(source_directories) and not any(library_directories):
			continue

		from time import time
		startup_millis = time()
		target_compiler_directory = join(target_directory, "classes", target.relative_directory)
		target_classes_directory = join(target_compiler_directory, "classes")
		ensure_directory(target_classes_directory)
		target_sources_directory = join(target_compiler_directory, "generated", "sources")
		ensure_directory(target_sources_directory)

		classes_listing = join(target_compiler_directory, ".classes")
		if not write_changed_source_files(target, source_directories, classes_listing):
			frozen(f"Directory {target.relative_directory!r} is not changed.")
			continue

		if not ecj_executable:
			java_executable = request_tool("java")
			if not java_executable:
				abort("Executable 'java' is required for compilation, nothing to do.")
			ecj_pattern = re.compile(r"ecj-(\d+\.)*jar")
			from .output_directory import get_config_directory
			ecj_executables = expand_paths(
				join(get_config_directory(), "bin/*"),
				lambda filename: isfile(filename) and re.fullmatch(ecj_pattern, basename(filename)) is not None
			)
			if len(ecj_executables) == 0:
				abort("Executable 'ecj-*.jar' is required for compilation, nothing to do.")
			ecj_executable = list()
			for executable in ecj_executables:
				ecj_executable = [java_executable, "-jar", executable]
				if request_executable_version(ecj_executable) != 0.0:
					break
			# TODO: error("Executable 'ecj-*.jar' is not supported, nothing to do.")

		options = list(target.manifest.options)
		if target.manifest.verbose:
			options.append("-verbose")
		if len(source_directories) > 0:
			options += ["-sourcepath", ":".join(join(target.directory, source) for source in source_directories)]
		precompiled = target.classpath
		if len(library_directories) > 0:
			precompiled += get_all_files((join(target.directory, library) for library in library_directories), (".jar"))
		options += ["-classpath", ":".join(precompiled)]

		result = subprocess.run(ecj_executable + [
			"--release", "8",
			"-Xlint",
			"-Xlint:-cast",
			"-Xemacs",
			"-proceedOnError",
			"-d", target_classes_directory,
			"-s", target_sources_directory
		] + options + [
			f"@{classes_listing}"
		], text=True, capture_output=True)
		startup_millis = time() - startup_millis
		if result.returncode == 0:
			success(f"Completed {target.relative_directory!r} compilation in {startup_millis:.2f}s!")
		else:
			pretty_error(result.stderr.strip())
			failure(f"Failed {target.relative_directory!r} compilation in {startup_millis:.2f}s with result {result.returncode}.")
			return result.returncode
	return 0

### GRADLE

def build_java_with_gradle(targets: Collection[BuildTarget], target_directory: str) -> int:
	setup_gradle_project(targets, target_directory, flatten_classpath_files(targets))
	if len(targets) != 0:
		from .output_directory import get_config_directory
		gradle_executable = join(get_config_directory(), "bin", "gradlew")
		if platform.system() == "Windows":
			gradle_executable += ".bat"

		options = list()
		for target in targets:
			if target.manifest.verbose:
				options += ["--console", "verbose"]
				break

		result = subprocess.run([
			gradle_executable,
			"-p", target_directory, "shadowJar"
		] + options)
		# if result.returncode != 0:
			# fallback = result.stderr.splitlines()
			# if "Could not initialize class org.codehaus.groovy.runtime.InvokerHelper" in fallback or \
					# "java.lang.NoClassDefFoundError: Could not initialize class org.codehaus.groovy.vmplugin.v7.Java7" in fallback:
				# attention("It seems that you are using an incompatible version of Java. We need OpenJDK 8 to compile sources (e.g., https://github.com/corretto/corretto-8/releases).")
			# else:
				# failure(result.stderr.strip())
			# return result.returncode
		pretty_print()

	cleanup_gradle_scripts(targets)
	return result.returncode if len(targets) != 0 else 0

def setup_gradle_project(targets: Collection[BuildTarget], target_directory: str, classpath: Collection[str]) -> None:
	with open(join(target_directory, "settings.gradle"), "w", encoding="utf-8") as settings_gradle:
		for target in targets:
			settings_gradle.write(f'include ":{target.relative_directory}"')
			settings_gradle.write(os.linesep)
			project_directory = target.directory.replace("\\", "\\\\")
			settings_gradle.write(f'project(":{target.relative_directory}").projectDir = file("{project_directory}")')
			settings_gradle.write(os.linesep)

	target_classes_directory = join(target_directory, "classes")
	ensure_directory(target_classes_directory)
	for target in targets:
		if not GLOBALS.MAKE_CONFIG.get_value("java.configurable", False) or not exists(join(target.directory, "build.gradle")):
			source_directories = list(target.manifest.sources)
			library_directories = list(target.manifest.libraries)
			write_build_gradle(target.directory, classpath, target_classes_directory, source_directories, library_directories)

def write_build_gradle(directory: str, classpath: Collection[str], target_classes_directory: str, source_directories: Collection[str], library_directories: Collection[str]) -> None:
	with open(join(directory, "build.gradle"), "w", encoding="utf-8") as build_gradle:
		build_gradle.write(
"""plugins {
	id "com.github.johnrengelman.shadow" version "5.2.0"
	id "java"
}

dependencies {
	""" + ("""compile fileTree(\"""" + "\", \"".join([
			path.replace("\\", "\\\\") for path in library_directories
		])
		+ """\") { include \"*.jar\" }""" if len(library_directories) > 0 else "") + """
}

sourceSets {
	main {
		java {
			srcDirs = [\"""" + "\", \"".join([
				path.replace("\\", "\\\\") for path in source_directories
			]) + """\"]
			buildDir = \"""" + join(target_classes_directory, "${project.name}").replace("\\", "\\\\") + """\"
		}
		resources {
			srcDirs = []
		}""" + (("""
		compileClasspath += files(\"""" + "\", \"".join([
			path.replace("\\", "\\\\") for path in classpath
		]) + "\")") if len(classpath) > 0 else "") + """
	}
}
""")

def cleanup_gradle_scripts(targets: Collection[BuildTarget]) -> None:
	if not GLOBALS.MAKE_CONFIG.get_value("java.configurable", False):
		for target in targets:
			gradle_script = join(target.directory, "build.gradle")
			if isfile(gradle_script):
				os.remove(gradle_script)

### TASKS

def get_java_build_targets(directories: Iterable[MakeJavaData]) -> List[BuildTarget]:
	targets = list()

	for java_data in directories:
		directory = GLOBALS.MAKE_CONFIG.get_path(java_data.relative_path)
		target = GLOBALS.PROJECT_STRUCTURE.declare_target("java", java_data.output_path)
		ensure_directory(target.absolute_path)
		classpath = collect_classpath_files(list(java_data.classpath))
		# XXX: Probably relative path (second argument) should be relative to project directory.
		target = BuildTarget(directory, java_data.output_path, target.absolute_path, java_data, classpath)
		targets.append(target)

	return targets

def build_java_directories(tool: str, directories: Iterable[MakeJavaData], target_directory: str) -> int:
	tool = tool if tool in ("javac", "ecj", "gradle") else "javac"
	GLOBALS.MAKE_CONFIG.bisect_properties(tool)
	targets = get_java_build_targets(directories)

	if tool == "gradle":
		result = build_java_with_gradle(targets, target_directory)
	elif tool == "ecj":
		result = build_java_with_ecj(targets, target_directory)
	else: # javac
		result = build_java_with_javac(targets, target_directory)
	if result != 0:
		GLOBALS.MAKE_CONFIG.remove_rules("java_compiler")
		return result

	modified_targets = update_modified_targets(targets, target_directory)
	for target in targets:
		if target.relative_directory not in modified_targets:
			# Otherwise it will be reported immediately.
			if tool == "gradle":
				frozen(f"Directory {target.relative_directory!r} is not changed.")
		else:
			pretty_info(f"* Running d8 with {target.relative_directory!r}")
			result = run_d8(target, modified_targets[target.relative_directory], target.classpath, target_directory)
			if result != 0:
				failure(f"Failed to dex {target.relative_directory!r} with result {result}.")
				GLOBALS.MAKE_CONFIG.remove_rules("java_compiler")
				return result
			result = merge_compressed_dexes(target, target_directory)
			if result != 0:
				failure(f"Failed to merge {target.relative_directory!r} with result {result}.")
				GLOBALS.MAKE_CONFIG.remove_rules("java_compiler")
				return result

		built_successfully = False

		target_odex_directory = join(target_directory, "odex", target.relative_directory)
		for dirpath, dirnames, filenames in os.walk(target_odex_directory):
			for filename in filenames:
				relative_directory = relpath(dirpath, target_odex_directory)
				copy_file(join(dirpath, filename), join(target.output_directory, relative_directory, filename))
				built_successfully = True

		for filename in os.listdir(target.directory):
			filepath = join(target.directory, filename)
			if splitext(filename)[1] == ".dex" and isfile(filepath):
				copy_file(filepath, join(target.output_directory, get_next_filename(target.output_directory, "classes", extension=".dex", start_index=2)))
				built_successfully = True

		if built_successfully:
			target_classes_directory = join(target_directory, "classes", target.relative_directory, "classes")
			if isdir(target_classes_directory):
				classpath_jar = join(target.output_directory, "classpath.jar")
				if isfile(classpath_jar):
					os.remove(classpath_jar)
				with ZipFile(classpath_jar, "w") as archive:
					walk_all_files(target_classes_directory, lambda path: archive.write(path, arcname=relpath(path, target_classes_directory)))

				classes_jar = join(target.output_directory, "classes.jar")
				if isfile(classes_jar):
					os.remove(classes_jar)
				with ZipFile(classes_jar, "w") as archive:
					walk_all_files(target_classes_directory, lambda path: archive.write(path, arcname=relpath(path, target_classes_directory)))

					lib_classes_dir = join(target_directory, "libraries", "classes", target.relative_directory)
					if isdir(lib_classes_dir):
						walk_all_files(lib_classes_dir, lambda path: archive.write(path, arcname=relpath(path, lib_classes_dir)))

			if target.manifest.keep_sources:
				target_sources_directory = join(target_directory, "classes", target.relative_directory, "generated", "sources")
				sources_jar = join(target.output_directory, "classpath-sources.jar")
				if isfile(sources_jar):
					os.remove(sources_jar)

				with ZipFile(sources_jar, "w") as archive:
					has_sources = False
					if isdir(target_sources_directory):
						walk_all_files(target_sources_directory, lambda path: archive.write(path, arcname=relpath(path, target_sources_directory)))
						has_sources = True

					for src_dir in target.manifest.sources:
						abs_src_dir = join(target.directory, src_dir)
						if isdir(abs_src_dir):
							walk_all_files(abs_src_dir, lambda path: archive.write(path, arcname=relpath(path, abs_src_dir)))
							has_sources = True

				if not has_sources and isfile(sources_jar):
					os.remove(sources_jar)

		if not built_successfully:
			attention(f"Directory {target.relative_directory!r} is empty.")

	if GLOBALS.MAKE_CONFIG.project_type == PROJECT_TYPE_PACK:
		target_output_path = GLOBALS.PROJECT_STRUCTURE.get("java").output_directory
		order = [relpath(target.output_directory, target_output_path) for target in targets]
		order_path = join(target_output_path, "order.txt")
		ensure_file(order_path)

		with open(order_path, "w", encoding="utf-8") as order_file:
			order_file.write("\n".join(order))
			order_file.write("\n")

	copy_additional_sources(targets)
	GLOBALS.MAKE_CONFIG.remove_rules("java_compiler")
	GLOBALS.BUILD_STORAGE.save()
	return result

def compile_java(tool: str = "gradle") -> int:
	if tool not in ("gradle", "javac", "ecj"):
		failure(f"Java compilation will be cancelled, because tool {tool!r} is not available.")
		return 255
	from time import time
	startup_millis = time()
	target_directory = GLOBALS.MAKE_CONFIG.get_build_path(tool)
	ensure_directory(target_directory)
	GLOBALS.PROJECT_STRUCTURE.cleanup_target("java")

	classpath_directories = list()
	classpath_directory = GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("classpath")
	if not isdir(classpath_directory):
		from .output_directory import get_config_directory
		classpath_directory = join(get_config_directory(), "classpath")
	project_classpath_directory = GLOBALS.MAKE_CONFIG.get_relative_path("classpath")
	if exists(project_classpath_directory):
		classpath_directories.append(project_classpath_directory)

	toolchain_config = None
	if len(classpath_directories) > 0:
		toolchain_config = Config()
		toolchain_config.set_value("classpath", classpath_directories)

	directories = GLOBALS.MAKE_CONFIG.iterate_java(defaults=toolchain_config)
	directories, has_anything = tee(directories)
	try:
		next(has_anything)
	except StopIteration:
		GLOBALS.project_structure.generate_config()
		return 0
	if not isdir(classpath_directory):
		attention("Not found 'classpath', in most cases build will be failed, please install it via tasks.")

	from .output_directory import get_config_directory
	r8_executable = join(get_config_directory(), "r8", "r8.jar")
	if not isfile(r8_executable):
		from .component import install_components
		install_components("java")
	if not isfile(r8_executable):
		abort("Component 'java' is required for compilation, nothing to do.")

	overall_result = build_java_directories(tool, directories, target_directory)

	GLOBALS.PROJECT_STRUCTURE.generate_config()
	if overall_result != -1:
		startup_millis = time() - startup_millis
		if overall_result == 0:
			success(f"Completed java build in {startup_millis:.2f}s!")
		else:
			failure(f"Failed java build in {startup_millis:.2f}s with result {overall_result}.")
	return max(0, overall_result)
