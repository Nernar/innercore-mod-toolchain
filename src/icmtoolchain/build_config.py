from functools import cmp_to_key
from os.path import basename, isfile, join, splitext
from typing import Iterable, Optional, override

from .config import Config, FileConfig
from .language import (PROJECT_TYPE_MOD, MakeAssetData, MakeDataConfig,
                       MakeJavaData, MakeModData, MakeNativeData,
                       MakeResourceData, MakeScriptData)
from .utils import ensure_not_whitespace

VALID_SOURCE_TYPES = ("mod", "launcher", "preloader", "instant", "custom", "library")
VALID_RESOURCE_TYPES = ("resource", "gui")

class BuildConfig(MakeDataConfig):
	def __init__(self, path: str, defaults: FileConfig) -> None:
		super().__init__(path, defaults)

	@property
	@override
	def project_type(self) -> int:
		return PROJECT_TYPE_MOD

	@override
	def obtain_project_data(self) -> Optional[MakeModData]:
		mod_info_file = self.get_relative_path("mod.info")
		if isfile(mod_info_file):
			mod_info = FileConfig(mod_info_file)
			return self.obtain_mod_data(mod_info)

	@property
	@override
	def supports_scripts(self) -> bool:
		return True

	@override
	def iterate_scripts(self) -> Iterable[MakeScriptData]:
		if self.get_value("defaultConfig.buildType") == "release":
			# XXX: Perhaps we should do something, but scripts may no longer exist.
			# It is important to leave a `compile`` field to load them.
			return

		library_path = self.get_value("defaultConfig.libraryDir")
		if ensure_not_whitespace(library_path):
			yield MakeScriptData(
				relative_path=f"{library_path}/*",
				output_path=basename(library_path),
				type="library"
			)

		sources_list = filter(
			lambda source: isinstance(source, Config),
			self.obtain_list("compile")
		)
		for source in sorted(sources_list, key=cmp_to_key(
			lambda a, b: \
				0 if a.get_value("sourceType") == "library" and b.get_value("sourceType") == "library" \
					else -1 if a.get_value("sourceType") == "library" else 1
		)):
			yield self.obtain_script_data(source)

	def obtain_script_data(self, source: Config) -> MakeScriptData:
		relative_path = source.get_value_unsafe("path")
		type = source.get_value_unsafe("type")
		if not type in VALID_SOURCE_TYPES:
			raise ValueError(f"Script {relative_path!r} has invalid type, it should be one of: {', '.join(VALID_SOURCE_TYPES)}!")

		build_directory = next(
			filter(lambda directory: isinstance(directory, Config) \
		  		and relative_path == directory.get_value("targetSource"), self.obtain_list("buildDirs")
			), None)
		if relative_path and build_directory:
			relative_path = build_directory.get_value("dir")
			output_path = source.get_value_unsafe("path")
		# Using template <sourceName>.<extension> -> <sourceName>, e.g. main.js -> main
		else:
			script_path = self.get_relative_path(relative_path)
			output_path = basename(script_path)
			if isfile(script_path):
				output_path = splitext(output_path)[0] + ".js"

		return MakeScriptData(
			relative_path=relative_path,
			output_path=output_path,
			type=type if type != "mod" else "main",
			source_name=source.get_value("sourceName"),
			api=source.get_value("api", lambda: source.get_value("defaultConfig.api")),
			optimization_level=source.get_value("optimizationLevel", lambda: source.get_value("defaultConfig.optimizationLevel", -1))
		)

	@property
	@override
	def supports_java(self) -> bool:
		return True

	@override
	def iterate_java(self, defaults: Optional[Config] = None) -> Iterable[MakeJavaData]:
		java_directories = self.obtain_list("javaDirs")
		for config in java_directories:
			if not isinstance(config, Config):
				continue
			if isinstance(defaults, Config):
				defaults_copy = Config(defaults)
				defaults_copy.merge_config(config, exclusive_lists=True)
				config = defaults_copy
			yield self.obtain_java_data(config)

	def obtain_java_data(self, config: Config) -> MakeJavaData:
		relative_path = config.get_value_unsafe("path")
		directory = self.get_path(relative_path)
		output_path = basename(directory)

		manifest_path = join(directory, "manifest")
		manifest = FileConfig(manifest_path, raise_non_existing=True)
		manifest.delete_value("path")
		config.merge_config(manifest, exclusive_lists=True)

		return self.obtain_java_manifest_data(relative_path=relative_path, output_path=output_path, config=config)

	@property
	@override
	def supports_native(self) -> bool:
		return True

	@override
	def iterate_native(self, defaults: Optional[Config] = None) -> Iterable[MakeNativeData]:
		native_directories = self.obtain_list("nativeDirs")
		for config in native_directories:
			if not isinstance(config, Config):
				continue
			if isinstance(defaults, Config):
				defaults_copy = Config(defaults)
				defaults_copy.merge_config(config, exclusive_lists=True)
				config = defaults_copy
			yield self.obtain_native_data(config)

	def obtain_native_data(self, config: Config) -> MakeNativeData:
		relative_path = config.get_value_unsafe("path")
		directory = self.get_path(relative_path)
		output_path = basename(directory)

		manifest_path = join(directory, "manifest")
		manifest = FileConfig(manifest_path)
		manifest.delete_value("path")
		config.merge_config(manifest, exclusive_lists=True)

		return self.obtain_native_manifest_data(relative_path=relative_path, output_path=output_path, config=config)

	@property
	@override
	def supports_resources(self) -> bool:
		return True

	@override
	def iterate_resources(self) -> Iterable[MakeResourceData]:
		resource_directories = self.obtain_list("resources")
		for source in resource_directories:
			if not isinstance(source, Config):
				continue
			yield self.obtain_resource_data(source)

		resource_packs = self.get_value("defaultConfig.resourcePacksDir")
		if ensure_not_whitespace(resource_packs):
			yield MakeResourceData(
				relative_path=f"{resource_packs}/*",
				output_path=basename(resource_packs),
				type="minecraft_resource_pack"
			)

		behavior_packs = self.get_value("defaultConfig.behaviorPacksDir")
		if ensure_not_whitespace(behavior_packs):
			yield MakeResourceData(
				relative_path=f"{behavior_packs}/*",
				output_path=basename(behavior_packs),
				type="minecraft_behavior_pack"
			)

	def obtain_resource_data(self, source: Config) -> MakeResourceData:
		relative_path = source.get_value_unsafe("path")
		type = source.get_value_unsafe("resourceType")
		if type not in VALID_RESOURCE_TYPES:
			raise ValueError(f"Resource {relative_path!r} has invalid type, it should be one of: {', '.join(VALID_RESOURCE_TYPES)}!")

		return MakeResourceData(
			relative_path=relative_path,
			output_path=basename(relative_path),
			type="resource_directory" if type == "resource" else type,
			push_unchanged_files=source.get_value("pushUnchangedFiles"),
			cleanup_remote=source.get_value("cleanupRemote")
		)

	@override
	def iterate_assets(self) -> Iterable[MakeAssetData]:
		# TODO: Probably do something like resource copying, probably keep them in place...
		...
