from abc import ABCMeta, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from os.path import abspath, basename, dirname, isdir, isfile, join
from typing import (TYPE_CHECKING, Any, Callable, Dict, Final, Iterable,
                    MutableMapping, Optional, Union)

from .config import Config, FileConfig
from .output_directory import expand_paths
from .shell import abort, warn
from .utils import RuntimeCodeError, ensure_not_whitespace

if TYPE_CHECKING:
	from .project_manager import Artifact

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
	manifest: MutableMapping[str, Any] = field(default_factory=Config)

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
	libraries: Iterable[str] = field(default_factory=list)
	classpath: Iterable[str] = field(default_factory=list)
	verbose: bool = False
	keep_libraries: bool = False
	keep_sources: bool = False
	options: Iterable[str] = field(default_factory=list)

@dataclass
class MakeNativeData:
	relative_path: str
	output_path: str
	shared_name: str
	depends: Iterable[str]
	link: Iterable[str] = field(default_factory=list)
	link_static: Iterable[str] = field(default_factory=list)
	include: Iterable[str] = field(default_factory=list)
	stdincludes: Iterable[str] = field(default_factory=list)
	keep_includes: bool = False
	keep_sources: bool = False
	options: Iterable[str] = field(default_factory=list)

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

AVAILABLE_DATA_CONFIGS: Dict[Union[str, Callable[[str], str]], type['MakeDataConfig']] = {}

class MakeDataConfig(FileConfig, metaclass=ABCMeta):
	defaults: FileConfig
	current_project: Final[str]
	project_unique_name: Final[str]

	def __init__(self, path: str, defaults: FileConfig) -> None:
		if not isfile(path):
			abort(f"Not found {basename(path)!r}, are you sure that selected project exists?")
		self.current_project = dirname(abspath(path))
		super().__init__(path, defaults, raise_non_existing=True)
		from .output_directory import unique_folder_name
		self.project_unique_name = unique_folder_name(self.directory)

	def get_build_path(self, *components: str) -> str:
		from .output_directory import get_temporary_directory
		return join(get_temporary_directory(), "build", self.project_unique_name, *components)

	@property
	def is_pack(self) -> bool:
		"""Packs should describe extra build data through special files that are only available to them.

		Returns:
			bool: whether or not to create a pack structure
		"""
		return False

	def iterate_dependencies(self) -> Iterable[Union['MakeDataConfig', 'Artifact']]:
		"""Each project may contain dependencies that must be compiled before that project itself.
		When instantiating a config, toolchain will make a dependency graph first, and only then build your project.

		Returns:
			Iterable[MakeDataConfig]: optional project data on which manifest is based
		"""
		...

	@abstractmethod
	def obtain_project_data(self) -> Optional[Union[MakeModData, MakePackData]]:
		"""Basic data describing this config and project as a whole. They should be provided in any case.
		If there is no value, no built-in startup configurations are created.

		Returns:
			Optional[Union[MakeModData, MakePackData]]: optional project data on which manifest is based
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

	def iterate_java(self, defaults: Optional[Config] = None) -> Iterable[MakeJavaData]:
		"""Returns iterable java data that is used in appropriate compilers and handlers.
		Java represents folders in their respective language, compiled using Javac.
		You are responsible for producing this data, using this config and manifests within a project.

		Returns:
			Iterable[MakeJavaData]: iterable which can be used in compilers
		"""
		...

	def obtain_java_manifest_data(self, relative_path: str, output_path: str, config: Config) -> MakeJavaData:
		return MakeJavaData(
			relative_path=relative_path,
			output_path=output_path,
			sources=config.obtain_list("source-dirs"),
			libraries=config.obtain_list("library-dirs"),
			classpath=config.obtain_list("classpath"),
			verbose=config.get_value("verbose", False),
			keep_libraries=config.get_value("keepLibraries", False),
			keep_sources=config.get_value("keepSources", False),
			options=config.obtain_list("options")
		)

	@property
	def supports_native(self) -> bool:
		return False

	def iterate_native(self, defaults: Optional[Config] = None) -> Iterable[MakeNativeData]:
		"""Returns iterable native data that is used in appropriate compilers and handlers.
		Native represents folders that uses C/C++ languages, compiled using GNU GCC.
		You are responsible for producing this data, using this config and manifests within a project.

		Returns:
			Iterable[MakeNativeData]: iterable which can be used in compilers
		"""
		...

	def obtain_native_manifest_data(self, relative_path: str, output_path: str, config: Config) -> MakeNativeData:
		# Obtain deprecated `rules` property to being merged.
		if "rules" in config:
			rules_config = config.get_value("rules")
			if isinstance(rules_config, Config):
				config.merge_config(rules_config)

		shared_name = config.get_value("shared.name", basename(relative_path))
		if not ensure_not_whitespace(shared_name) or ("shared" in config and shared_name == "unnamed"):
			raise ValueError(f"Library directory {relative_path!r} uses illegal name {shared_name!r}!")
		if config.get_value("library.version", -1) < 0 and "library" in config:
			raise ValueError(f"Library directory {relative_path!r} shared a library with illegal version!")

		return MakeNativeData(
			relative_path=relative_path,
			output_path=output_path,
			shared_name=shared_name,
			depends=config.obtain_list("depends"),
			link=config.obtain_list("link"),
			link_static=config.obtain_list("linkStatic"),
			include=config.obtain_list("include"),
			stdincludes=config.obtain_list("stdincludes"),
			keep_includes=config.get_value("keepIncludes", False),
			keep_sources=config.get_value("keepSources", False),
			options=config.obtain_list("options")
		)

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

	@staticmethod
	def register(criteria: Union[str, Callable[[str], str]], data: type['MakeDataConfig']) -> None:
		"""Here you can check if this project can be loaded with this config.

		Args:
			criteria (Union[str, Callable[[str], bool]]): filter configs by filename or deeper callable inspection
			data (type[MakeDataConfig]): type to be created, which will become a config with data

		Raises:
			ValueError: if this criteria has already been registered earlier
		"""
		if criteria in AVAILABLE_DATA_CONFIGS:
			raise ValueError(f"Data criteria {criteria} already occupied by {AVAILABLE_DATA_CONFIGS[criteria]}!")
		AVAILABLE_DATA_CONFIGS[criteria] = data

	@staticmethod
	def of(directory: str) -> Optional['MakeDataConfig']:
		for criteria, config_type in AVAILABLE_DATA_CONFIGS.items():
			if isinstance(criteria, str):
				config_file = join(directory, criteria)
				if not isfile(config_file):
					continue
			elif callable(criteria):
				config_file = criteria(directory)
			else:
				continue
			if not config_file:
				continue
			from . import GLOBALS
			return config_type(config_file, defaults=GLOBALS.TOOLCHAIN_CONFIG)

class AbobaConfig(MakeDataConfig):
	def __init__(self, key: str) -> None:
		from . import GLOBALS
		if not isfile(GLOBALS.TOOLCHAIN_CONFIG.path):
			from os import makedirs
			from os.path import dirname
			makedirs(dirname(GLOBALS.TOOLCHAIN_CONFIG.path))
			with open(GLOBALS.TOOLCHAIN_CONFIG.path, "x") as file:
				file.write("{}")
		super().__init__(GLOBALS.TOOLCHAIN_CONFIG.path, GLOBALS.TOOLCHAIN_CONFIG)
		self.key = key

	def __hash__(self):
		return hash(frozenset(self)) ^ hash(self.key)

	@property
	def is_pack(self) -> bool:
		return False

	def iterate_dependencies(self) -> Iterable[Union['MakeDataConfig', 'Artifact']]:
		return []

	def obtain_project_data(self) -> Optional[Union[MakeModData, MakePackData]]:
		pass

	def iterate_assets(self) -> Iterable[MakeAssetData]:
		return []
