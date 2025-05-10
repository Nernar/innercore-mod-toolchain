from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from functools import cmp_to_key
from os.path import basename, isfile, join
from posixpath import splitext
from typing import (Any, Final, Iterable, MutableMapping, Optional, Sequence,
                    Union, override)

from .config import Config, FileConfig
from .shell import abort


@dataclass
class MakeModData:
	name: str
	author: str
	version: str = "1.0"
	description: str = ""
	icon: Optional[str] = "mod_icon.png"

@dataclass
class MakePackData:
	name: str
	version: str
	description: Union[MutableMapping[str, str], str] = ""
	manifest: MutableMapping[str, Any] = Config()

@dataclass
class MakeScriptData:
	relative_path: str
	output_path: str
	type: str = "main"
	language: Optional[str] = None
	source_name: Optional[str] = None
	api: str = "CoreEngine"
	includes_path: str = ".includes"
	optimization_level: int = -1

@dataclass
class MakeJavaData:
	relative_path: str
	output_path: str
	sources: Iterable[str]
	libraries: Iterable[str] = []
	classpath: Iterable[str] = []
	keep_libraries: bool = False
	keep_sources: bool = False
	options: Iterable[str] = []

@dataclass
class MakeNativeData:
	relative_path: str
	output_path: str
	shared_name: str
	depends: Iterable[str]
	link: Iterable[str] = []
	include: Iterable[str] = []
	stdincludes: Iterable[str] = []
	keep_includes: bool = False
	keep_sources: bool = False
	options: Iterable[str] = []

@dataclass
class MakeSharedObjectData:
	relative_path: str
	output_path: str

@dataclass
class MakeResourceData:
	relative_path: str
	output_path: str
	type: str = "resource_directory"
	push_unchanged_files: bool = True
	cleanup_remote: bool = True

@dataclass
class MakeAssetData:
	relative_path: str
	output_path: str
	output_filename: Optional[str] = None
	push_unchanged_files: bool = True
	cleanup_remote: bool = True

class MakeDataConfig(FileConfig, metaclass=ABCMeta):
	defaults: FileConfig
	current_project: Final[str]
	project_unique_name: Final[str]

	def __init__(self, path: str, defaults: FileConfig) -> None:
		if not isfile(path):
			abort(f"Not found {basename(path)!r}, are you sure that selected project exists?")
		self.current_project = defaults.get_value("currentProject")
		super().__init__(path, defaults, raise_non_existing=True)
		from .output_directory import unique_folder_name
		self.project_unique_name = unique_folder_name(self.directory)

	def get_build_path(self, relative_path: str) -> str:
		return self.defaults.get_relative_path(join("build", self.project_unique_name, relative_path))

	@property
	@abstractmethod
	def project_data(self) -> Optional[Union[MakeModData, MakePackData]]:
		"""Basic data describing this config and project as a whole. They should be provided in any case.
		If there is no value, no built-in startup configurations are created.

		Returns:
			Union[MakeModData, MakePackData]: project data on which manifest is based
		"""
		...

	def obtain_mod_data(self, mod_info: Config) -> MakeModData:
		name = mod_info.get_value("name") or "Wholesome Mod"
		author = mod_info.get_value("author") or "ICMods"
		version = mod_info.get_value("version") or "1.0"
		description = mod_info.get_value("description") or ""
		icon = mod_info.get_value("icon") or "mod_icon.png"

		from .utils import shortcodes
		return MakeModData(
			name=shortcodes(name),
			author=author,
			version=shortcodes(version),
			description=shortcodes(description),
			icon=icon
		)

	def obtain_pack_data(self, manifest: Config) -> MakePackData:
		name = manifest.get_value("pack") or "Wholesome Pack"
		version = manifest.get_value("packVersion") or "1.0"
		description = manifest.get_value("description") or ""

		from .utils import shortcodes
		if isinstance(description, MutableMapping):
			for key, value in description.items():
				description[key] = shortcodes(value)
		else:
			description = shortcodes(description)
		return MakePackData(
			name=shortcodes(name),
			version=shortcodes(version),
			description=description
		)

	@property
	def supports_scripts(self) -> bool:
		return False

	def iterate_scripts(self) -> Iterable[MakeScriptData]:
		"""Returns iterable script data that is used in appropriate compilers and handlers.
		Scripts are individual files or folders written using Java/TypeScript language.
		You are responsible for producing this data, using this config and manifests within a project.

		Returns:
			Iterable[MakeScriptData]: iterable which can be used in compilers
		"""
		...

	@property
	def supports_java(self) -> bool:
		return False

	def iterate_java(self) -> Iterable[MakeJavaData]:
		"""Returns iterable java data that is used in appropriate compilers and handlers.
		Java represents folders in their respective language, compiled using Javac.
		You are responsible for producing this data, using this config and manifests within a project.

		Returns:
			Iterable[MakeJavaData]: iterable which can be used in compilers
		"""
		...

	@property
	def supports_native(self) -> bool:
		return False

	def iterate_native(self) -> Iterable[MakeNativeData]:
		"""Returns iterable native data that is used in appropriate compilers and handlers.
		Native represents folders that uses C/C++ languages, compiled using GNU GCC.
		You are responsible for producing this data, using this config and manifests within a project.

		Returns:
			Iterable[MakeNativeData]: iterable which can be used in compilers
		"""
		...

	@property
	def supports_shared_objects(self) -> bool:
		return False

	def iterate_shared_objects(self) -> Iterable[MakeSharedObjectData]:
		"""Returns iterable shared object data that is used in appropriate compilers and handlers.
		Shared objects are platform-specific native libraries. They are precompiled.
		You are responsible for producing this data, using this config and manifests within a project.

		Returns:
			Iterable[MakeSharedObjectData]: iterable which can be used in compilers
		"""
		...

	@property
	def supports_resources(self) -> bool:
		return False

	def iterate_resources(self) -> Iterable[MakeResourceData]:
		"""Returns iterable resource data that is used in appropriate compilers and handlers.
		Resources are textures, shaders, and other materials that extend a game. There are different types of resources.
		You are responsible for producing this data, using this config and manifests within a project.

		Returns:
			Iterable[MakeResourceData]: iterable which can be used in compilers
		"""
		...

	@abstractmethod
	def iterate_assets(self) -> Iterable[MakeAssetData]:
		"""Returns iterable asset data that is used in appropriate compilers and handlers.
		Assets are usually extra files, they are located in project folder and should be defined in your config.
		You are responsible for producing this data, using this config and manifests within a project.

		Returns:
			Iterable[MakeAssetData]: iterable which can be used in compilers
		"""
		...

class MakeConfig(MakeDataConfig):
	def __init__(self, path: str, defaults: FileConfig) -> None:
		super().__init__(path, defaults)
		if "make.json" == basename(path):
			self.migrate_make_config(self)
		if "toolchain.json" == basename(defaults.path):
			self.migrate_make_config(defaults)
		self.is_pack = "manifest" in self

	def migrate_make_config(self, config: FileConfig, save_then: bool = True) -> bool:
		changes = False
		if "global" in config:
			global_config = config.get_value("global", dict())
			for entry in global_config:
				config.set_value(entry, global_config[entry])
			config.delete_value("global")
			changes |= True
		if "make" in config:
			make_config = config.get_value("make", dict())
			if "linkNative" in make_config:
				config.set_value("linkNative", make_config["linkNative"])
			if "excludeFromRelease" in make_config:
				config.set_value("excludeFromRelease", make_config["excludeFromRelease"])
			config.delete_value("make")
			changes |= True
		if "gradle" in config:
			gradle_config = config.get_value("gradle", dict())
			java_config = config.get_value("java", dict())
			for entry in gradle_config:
				java_config.set_value(entry, gradle_config[entry])
			config.set_value("java", java_config)
			config.delete_value("gradle")
			changes |= True
		if save_then and changes:
			config.save_as_file()
		return changes

	@property
	@override
	def project_data(self) -> Optional[Union[MakeModData, MakePackData]]:
		if not self.is_pack and "info" in self:
			mod_info = self.obtain_config("info")
			return self.obtain_mod_data(mod_info)
		if self.is_pack and "manifest" in self:
			manifest_relative_path = self.get_value("manifest")
			manifest_path = self.get_relative_path(manifest_relative_path)
			manifest = FileConfig(manifest_path, raise_non_existing=True)
			return self.obtain_pack_data(manifest)

	@property
	@override
	def supports_scripts(self) -> bool:
		return not self.is_pack

	@override
	def iterate_scripts(self) -> Iterable[MakeScriptData]:
		sources_list = filter(
			lambda source: isinstance(source, Config),
			self.obtain_list("sources")
		)
		for source in sorted(sources_list, key=cmp_to_key(
			lambda a, b: \
				0 if a.get_value("type") == "library" and b.get_value("type") == "library" \
					else -1 if a.get_value("type") == "library" else 1
		)):
			yield self.obtain_script_data(source)

	def obtain_script_data(self, source: Config) -> MakeScriptData:
		relative_path = source.get_value_unsafe("source")
		from .script_build import VALID_SOURCE_TYPES
		type = source.get_value_unsafe("type")
		if not type in VALID_SOURCE_TYPES:
			raise ValueError(f"Script {relative_path!r} has invalid type, it should be one of: {', '.join(VALID_SOURCE_TYPES)}!")
		language = source.get_value("language")
		if language and language not in ("javascript", "typescript"):
			raise ValueError(f"Script {relative_path!r} has invalid language, it should be 'javascript' or 'typescript'!")

		output_path = source.get_value("target")
		if not output_path:
			script_path = self.get_relative_path(relative_path)
			output_path = basename(script_path)
			if isfile(script_path):
				output_path = splitext(output_path)[0] + ".js"

		return MakeScriptData(
			relative_path=relative_path,
			output_path=output_path,
			type=type,
			language=language,
			source_name=source.get_value("sourceName", lambda: relative_path),
			api=source.get_value("api"),
			includes_path=source.get_value("includes"),
			optimization_level=source.get_value("optimizationLevel")
		)

	@property
	@override
	def supports_java(self) -> bool:
		return True

	@override
	def iterate_java(self) -> Iterable[MakeJavaData]:
		...

	@property
	@override
	def supports_native(self) -> bool:
		return True

	@override
	def iterate_native(self) -> Iterable[MakeNativeData]:
		...

	@property
	@override
	def supports_shared_objects(self) -> bool:
		return self.is_pack

	@override
	def iterate_shared_objects(self) -> Iterable[MakeSharedObjectData]:
		...

	@property
	@override
	def supports_resources(self) -> bool:
		return not self.is_pack

	@override
	def iterate_resources(self) -> Iterable[MakeResourceData]:
		for source in self.obtain_list("resources"):
			if not isinstance(source, Config):
				continue
			yield self.obtain_resource_data(source)

	def obtain_resource_data(self, source: Config) -> MakeResourceData:
		relative_path = source.get_value_unsafe("path")
		from .resources import VALID_RESOURCE_TYPES
		type = source.get_value_unsafe("type")
		if not type in VALID_RESOURCE_TYPES:
			raise ValueError(f"Resource {relative_path!r} has invalid type, it should be one of: {', '.join(VALID_RESOURCE_TYPES)}!")

		return MakeResourceData(
			relative_path=relative_path,
			output_path=basename(relative_path),
			type=type,
			push_unchanged_files=source.get_value("pushUnchangedFiles"),
			cleanup_remote=source.get_value("cleanupRemote")
		)

	@override
	def iterate_assets(self) -> Iterable[MakeAssetData]:
		for source in self.obtain_list("additional"):
			if not isinstance(source, Config):
				continue
			yield self.obtain_asset_data(source)

	def obtain_asset_data(self, source: Config) -> MakeAssetData:
		relative_path = source.get_value_unsafe("path")
		output_path = source.get_value_unsafe("targetDir")

		return MakeAssetData(
			relative_path=relative_path,
			output_path=output_path,
			output_filename=source.get_value("targetFile"),
			push_unchanged_files=source.get_value("pushUnchangedFiles"),
			cleanup_remote=source.get_value("cleanupRemote")
		)
