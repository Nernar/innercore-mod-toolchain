from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from os.path import basename, isfile, join
from typing import Any, Final, Iterable, MutableMapping, Optional, Union

from .config import Config, FileConfig
from .shell import abort


@dataclass
class MakeModData:
	name: str
	author: str
	version: str = "1.0"
	description: str = ""
	client_only: bool = False
	icon: Optional[str] = "mod_icon.png"

@dataclass
class MakePackData:
	name: str
	version: str
	description: Union[MutableMapping[str, str], str] = ""
	manifest: MutableMapping[str, Any] = Config()

@dataclass
class MakeScriptData:
	name: str
	relative_path: str
	output_path: str
	type: str = "main"
	language: Optional[str] = None
	api: str = "CoreEngine"
	includes_path: str = ".includes"
	optimization_level: int = -1
	declarations: Iterable[str] = []
	is_shared: bool = False

@dataclass
class MakeJavaData:
	name: str
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
	name: str
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
	name: str
	relative_path: str
	output_path: str

@dataclass
class MakeResourceData:
	name: str
	relative_path: str
	output_path: str
	type: str = "resource_directory"
	push_unchanged_files: bool = True
	cleanup_remote: bool = True

@dataclass
class MakeAssetData:
	name: str
	relative_path: str
	output_path: str
	push_unchanged_files: bool = True
	cleanup_remote: bool = True

class AbstractMakeConfig(FileConfig, metaclass=ABCMeta):
	def __init__(self, path: str, defaults: FileConfig) -> None:
		super().__init__(path, defaults, raise_non_existing=True)

	@property
	@abstractmethod
	def project_data(self) -> Union[MakeModData, MakePackData]:
		"""Basic data describing this config and project as a whole. They should be provided in any case.

		Returns:
			Union[MakeModData, MakePackData]: project data on which manifest is based
		"""
		return MakeModData("Wholesome Mod", "ICMods")

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

class MakeConfig(FileConfig):
	defaults: FileConfig
	current_project: Final[str]
	project_unique_name: Final[str]

	def __init__(self, path: str, defaults: FileConfig) -> None:
		if not isfile(path):
			abort(f"Not found {basename(path)!r}, are you sure that selected project exists?")
		self.current_project = defaults.get_value("currentProject")
		super().__init__(path, defaults=defaults)
		if "make.json" == basename(path):
			self.migrate_make_config(self)
		if "toolchain.json" == basename(defaults.path):
			self.migrate_make_config(defaults)
		from .output_directory import unique_folder_name
		self.project_unique_name = unique_folder_name(self.directory)

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

	def get_build_path(self, relative_path: str) -> str:
		return self.defaults.get_relative_path(join("build", self.project_unique_name, relative_path))
