import os
from itertools import tee
from os.path import basename, exists, isdir, isfile, join
from shutil import make_archive
from typing import MutableMapping

from . import GLOBALS
from .config import FileConfig
from .language import MakeModData, MakePackData
from .make_config import MakeConfig
from .output_directory import expand_paths
from .shell import debug, pretty_print, warn
from .utils import (copy_directory, copy_file, ensure_directory,
                    ensure_file_directory, ensure_not_whitespace, remove_tree)


def build_resources() -> int:
	GLOBALS.MOD_STRUCTURE.cleanup_build_target("resource_directory")
	GLOBALS.MOD_STRUCTURE.cleanup_build_target("gui")
	GLOBALS.MOD_STRUCTURE.cleanup_build_target("minecraft_resource_pack")
	GLOBALS.MOD_STRUCTURE.cleanup_build_target("minecraft_behavior_pack")
	overall_result = 0

	for resource in GLOBALS.MAKE_CONFIG.iterate_resources():
		resource_files = expand_paths(GLOBALS.MAKE_CONFIG.get_relative_path(resource.relative_path))
		if len(resource_files) == 0:
			warn(f"* Skipped non-existing resource {resource.relative_path!r}!")
			continue

		for source_path in resource_files:
			resource_name = basename(source_path)
			if resource.type in ("resource_directory", "gui"):
				target = GLOBALS.MOD_STRUCTURE.create_build_target(
					resource.type,
					resource_name,
					declare={
						"resourceType": "resource" if resource.type == "resource_directory" else resource.type
					}
				)
			else:
				target = GLOBALS.MOD_STRUCTURE.create_build_target(
					resource.type,
					resource_name,
					exclude=True,
					declare_default={
						"resourcePacksDir": GLOBALS.MOD_STRUCTURE.get_target_directories("minecraft_resource_pack")[0],
						"behaviorPacksDir": GLOBALS.MOD_STRUCTURE.get_target_directories("minecraft_behavior_pack")[0]
					}
				)

			relative_path = GLOBALS.MAKE_CONFIG.get_path_to_config(source_path)
			output_path = GLOBALS.MOD_STRUCTURE.build_targets[resource.type].directory + "/" + target["name"]
			GLOBALS.LINKED_RESOURCE_STORAGE.append_resource(
				relative_path,
				output_path,
				push_unchanged=resource.push_unchanged_files,
				cleanup_remote=resource.cleanup_remote
			)

	GLOBALS.MOD_STRUCTURE.update_build_config_list("resources")
	return overall_result

def build_pack_graphics() -> int:
	graphics_archive = join(GLOBALS.MOD_STRUCTURE.directory, "graphics.zip")
	if exists(graphics_archive):
		remove_tree(graphics_archive)
	graphics_groups = GLOBALS.MAKE_CONFIG.iterate_pack_graphics()
	graphics_groups, has_anything = tee(graphics_groups)
	try:
		next(has_anything)
	except StopIteration:
		return 0

	graphics_directory = GLOBALS.MAKE_CONFIG.get_build_path("graphics")
	remove_tree(graphics_directory)
	ensure_directory(graphics_directory)

	group_length = 0
	for graphics in graphics_groups:
		offset = 1
		for image_directory in graphics.images:
			for image_path in expand_paths(GLOBALS.MAKE_CONFIG.get_relative_path(image_directory)):
				if not isfile(image_path):
					warn(f"* Skipping graphics image file {basename(image_path)}, cause it does not exists!")
					continue
				copy_file(image_path, join(graphics_directory, f"{graphics.group_name}@{offset}.png"))
				offset += 1
		group_length += 1

	from shutil import make_archive
	make_archive(graphics_archive[:-4], "zip", graphics_directory)
	pretty_print(f"Composed a pack with graphics from {group_length} groups!")
	return 0

def build_additional_resources() -> int:
	overall_result = 0

	for asset in GLOBALS.MAKE_CONFIG.iterate_assets():
		additional_files = expand_paths(GLOBALS.MAKE_CONFIG.get_relative_path(asset.relative_path))
		if len(additional_files) == 0:
			warn(f"* Skipped non-existing additional resource {asset.relative_path!r}!")
			continue

		for additional_path in additional_files:
			relative_path = GLOBALS.MAKE_CONFIG.get_path_to_config(additional_path)
			output_relative_filename = ensure_not_whitespace(asset.output_filename, basename(additional_path))
			output_path = f"{asset.output_path}/{output_relative_filename}"

			debug(f"Referencing {asset.relative_path!r} to {output_path!r} on remote")
			GLOBALS.LINKED_RESOURCE_STORAGE.append_resource(
				relative_path,
				output_path,
				push_unchanged=asset.push_unchanged_files,
				cleanup_remote=asset.cleanup_remote
			)

	return overall_result

def write_mod_info_file(data: MakeModData) -> int:
	info_file = join(GLOBALS.MOD_STRUCTURE.directory, "mod.info")
	info = FileConfig(info_file, do_not_read=True)
	if not ensure_not_whitespace(data.name):
		info.set_value("name", data.name)
	if not ensure_not_whitespace(data.author):
		info.set_value("author", data.author)
	if not ensure_not_whitespace(data.version):
		info.set_value("version", data.version)
	if not ensure_not_whitespace(data.description):
		info.set_value("description", data.description)
	info.save_as_file()

	icon_path = GLOBALS.MAKE_CONFIG.get_path(data.icon or "mod_icon.png")
	output_info_path = join(GLOBALS.MOD_STRUCTURE.directory, "mod_icon.png")
	if isfile(icon_path) and icon_path != output_info_path:
		copy_file(icon_path, output_info_path)
	elif ensure_not_whitespace(data.icon):
		warn(f"* Icon {icon_path!r} described in 'make.json' is not found!")
	return 0

def write_manifest_file(data: MakePackData) -> int:
	output_manifest_path = join(GLOBALS.MOD_STRUCTURE.directory, "manifest.json")
	manifest = FileConfig(output_manifest_path, map=data.manifest, do_not_read=True)
	if ensure_not_whitespace(data.name):
		manifest.set_value("pack", data.name)
	if ensure_not_whitespace(data.version):
		manifest.set_value("packVersion", data.version)
	if isinstance(data.description, MutableMapping) or ensure_not_whitespace(data.description):
		manifest.set_value("description", data.description)
	manifest.save_as_file(output_manifest_path)
	return 0

def build_package() -> int:
	name = basename(GLOBALS.MAKE_CONFIG.current_project)
	output_directory = GLOBALS.MAKE_CONFIG.get_build_path("package")

	output_package_directory = join(output_directory, name)
	remove_tree(output_package_directory)

	output_temporary_file = join(output_directory, "package.zip")
	ensure_file_directory(output_temporary_file)
	remove_tree(output_temporary_file)
	output_file = GLOBALS.MAKE_CONFIG.get_relative_path(name + ".zip" if GLOBALS.MAKE_CONFIG.is_pack else name + ".icmod")
	ensure_file_directory(output_file)
	remove_tree(output_file)

	copy_directory(GLOBALS.MOD_STRUCTURE.directory, output_package_directory)
	for linked_resource in GLOBALS.LINKED_RESOURCE_STORAGE.iterate_resources():
		input_resource = GLOBALS.MAKE_CONFIG.get_relative_path(linked_resource["relative_path"])
		output_package_resource = join(output_package_directory, linked_resource["output_path"])
		if isfile(input_resource):
			copy_file(input_resource, output_package_resource)
		elif isdir(input_resource):
			copy_directory(input_resource, output_package_resource)
		else:
			warn(f"* We cannot copy {linked_resource['relative_path']} resource because we could not determine its type.")
	for path in GLOBALS.MAKE_CONFIG.obtain_list("excludeFromRelease"):
		for excluded_path in expand_paths(join(output_package_directory, path)):
			remove_tree(excluded_path)
	make_archive(output_temporary_file[:-4], "zip", output_directory, name)

	remove_tree(output_package_directory)
	os.rename(output_temporary_file, output_file)
	return 0
