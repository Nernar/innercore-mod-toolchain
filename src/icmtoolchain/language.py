from abc import ABCMeta, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from os.path import basename, isdir, isfile, join
from typing import (Any, Callable, Dict, Final, Iterable, MutableMapping,
                    Optional, Union)

from .config import Config, FileConfig
from .output_directory import expand_paths
from .shell import abort, warn
from .utils import RuntimeCodeError


def get_language_directories(compile_type: str, language_config: Config, properties_merger: Optional[Callable] = None, make_config: Optional['MakeDataConfig'] = None) -> Dict[str, Config]:
	if not make_config:
		from . import GLOBALS
		make_config = GLOBALS.MAKE_CONFIG

	directories = language_config.obtain_list("directories")
	if not any(directories):
		# Obtain directories from deprecated `compile` property.
		directories = list(filter(
			lambda source: isinstance(source, Config) and compile_type == source.get_value("type"),
			make_config.obtain_list("compile")
		))
	configurables = dict()
	if not any(directories):
		return configurables
	language_config.delete_value("directories")

	for directory in directories:
		config = None

		if isinstance(directory, Config):
			directory.defaults = config
			config = directory
			if "path" in directory:
				directory = directory.get_value("path")
			elif "source" in directory:
				directory = directory.get_value("source")
		if not isinstance(directory, str):
			raise RuntimeCodeError(1, f"Wrong declared {compile_type} directory {directory!r}, it should be path string or object with `path` property!")

		for flattened_directory in expand_paths(make_config.get_relative_path(directory)):
			absolute_directory = make_config.get_path(flattened_directory)
			if not isdir(absolute_directory):
				warn(f"* Skipped non-existing {compile_type} directory {directory!r}!")
				continue
			if absolute_directory in configurables:
				warn(f"* Duplicate {compile_type} directory {directory!r}, overriding existing properties...")

			if properties_merger:
				config = properties_merger(config, language_config)
			else:
				temporary_config = Config(deepcopy(language_config.as_json()))
				if config:
					temporary_config.merge_config(config, exclusive_lists=True)
				config = temporary_config
			config.set_value("directory", make_config.get_path_to_config(flattened_directory))
			configurables[absolute_directory] = config

	return configurables

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
	verbose: bool = False
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
	link_static: Iterable[str] = []
	include: Iterable[str] = []
	stdincludes: Iterable[str] = []
	keep_includes: bool = False
	keep_sources: bool = False
	options: Iterable[str] = []

@dataclass
class MakeSharedObjectData:
	relative_path: str

@dataclass
class MakeResourceData:
	relative_path: str
	output_path: str # XXX: Unused, at least for now.
	type: str = "resource_directory"
	push_unchanged_files: bool = True
	cleanup_remote: bool = True

@dataclass
class MakePackGraphicsData:
	group_name: str
	images: Iterable[str]

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

	@abstractmethod
	def obtain_project_data(self) -> Optional[Union[MakeModData, MakePackData]]:
		"""Basic data describing this config and project as a whole. They should be provided in any case.
		If there is no value, no built-in startup configurations are created.

		Returns:
			Union[MakeModData, MakePackData]: project data on which manifest is based
		"""
		...

	def obtain_mod_data(self, mod_info: Config) -> MakeModData:
		name = mod_info.get_value("name") or ""
		author = mod_info.get_value("author") or ""
		version = mod_info.get_value("version") or ""
		description = mod_info.get_value("description") or ""
		icon = mod_info.get_value("icon")

		from .utils import shortcodes
		return MakeModData(
			name=shortcodes(name),
			author=author,
			version=shortcodes(version),
			description=shortcodes(description),
			icon=icon
		)

	def obtain_pack_data(self, manifest: Config) -> MakePackData:
		name = manifest.get_value("pack") or ""
		version = manifest.get_value("packVersion") or ""
		description = manifest.get_value("description") or ""

		from .utils import shortcodes
		if isinstance(description, MutableMapping):
			for key, value in description.items():
				description[key] = shortcodes(value)
		elif isinstance(description, str):
			description = shortcodes(description)

		return MakePackData(
			name=shortcodes(name),
			version=shortcodes(version),
			description=description,
			manifest=manifest
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

	@property
	def supports_pack_graphics(self) -> bool:
		return False

	def iterate_pack_graphics(self) -> Iterable[MakePackGraphicsData]:
		"""Returns iterable pack graphics data that is used in appropriate compilers and handlers.
		Pack graphics are usually images for interactive window interfaces and backgrounds in pack menus.
		You are responsible for producing this data, using this config and manifests within a project.

		Returns:
			Iterable[MakePackGraphicsData]: iterable which can be used in compilers
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
