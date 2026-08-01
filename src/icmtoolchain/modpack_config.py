from os import scandir
from os.path import basename, exists, isdir, isfile, join
from typing import Iterable, MutableMapping, Optional, Union

from .config import Config, FileConfig
from .language import (PROJECT_TYPE_MODPACK, MakeAssetData, MakeDataConfig,
                       MakeModpackData)
from .project_graph import Artifact

DECLARED_MODPACK_DIRECTORY_TYPES = ("resource", "user_data", "config", "cache", "invalid")

class ModpackConfig(MakeDataConfig):
	def __init__(self, path: str, defaults: FileConfig) -> None:
		super().__init__(path, defaults)

	@property
	def project_type(self) -> int:
		return PROJECT_TYPE_MODPACK

	def iterate_dependencies(self) -> Iterable[Union[MakeDataConfig, Artifact]]:
		mod_directory = self.get_relative_path("mods")
		if not isdir(mod_directory):
			return

		resolved_dependencies = []
		for filefd in scandir(mod_directory):
			if not filefd.is_dir():
				continue
			dependency = MakeDataConfig.of(filefd.path)
			if dependency is not None:
				resolved_dependencies.append(dependency)

		active_side = self.get_active_side()
		for dependency in resolved_dependencies:
			resolved = dependency if isinstance(dependency, (MakeDataConfig, Artifact)) else self.resolve_dependency_entry(dependency)
			if resolved is None:
				continue
			if active_side and isinstance(resolved, MakeDataConfig):
				if not resolved.is_side_compatible(active_side):
					continue
			yield resolved

	def obtain_project_data(self) -> Optional[MakeModpackData]:
		return self.obtain_modpack_data(self)

	@property
	def supports_scripts(self) -> bool:
		return False

	@property
	def supports_java(self) -> bool:
		return False

	@property
	def supports_native(self) -> bool:
		return False

	@property
	def supports_resources(self) -> bool:
		return False

	def iterate_assets(self) -> Iterable[MakeAssetData]:
		modpack_assets = self.get_relative_path("mod_assets")
		if isdir(modpack_assets):
			yield MakeAssetData(
				relative_path=self.get_path_to_config(modpack_assets),
				output_path="mod_assets"
			)
		for directory in self.obtain_list("directories"):
			if not isinstance(directory, MutableMapping):
				continue
			directory_config = Config(map=directory)
			try:
				yield self.obtain_asset_data(directory_config)
			except ValueError as exc:
				from .logger import attention
				attention(exc)
		external_servers = self.get_relative_path("external_servers.txt")
		if isfile(external_servers):
			yield MakeAssetData(
				relative_path=self.get_path_to_config(external_servers),
				output_path="mod_assets"
			)
		resource_packs = self.get_relative_path("resource_packs")
		if isdir(resource_packs):
			yield MakeAssetData(
				relative_path=self.get_path_to_config(resource_packs),
				output_path="resource_packs"
			)
		behavior_packs = self.get_relative_path("behavior_packs")
		if isdir(behavior_packs):
			yield MakeAssetData(
				relative_path=self.get_path_to_config(behavior_packs),
				output_path="behavior_packs"
			)
		texture_packs = self.get_relative_path("texture_packs")
		if isdir(texture_packs):
			yield MakeAssetData(
				relative_path=self.get_path_to_config(texture_packs),
				output_path="texture_packs"
			)

	def obtain_asset_data(self, source: Config) -> MakeAssetData:
		relative_path = source.get_value("path")
		type = source.get_value("type")
		if not type in DECLARED_MODPACK_DIRECTORY_TYPES:
			raise ValueError(f"Modpack directory {relative_path!r} has invalid type, it should be one of: {', '.join(DECLARED_MODPACK_DIRECTORY_TYPES)}!")
		absolute_path = self.get_path(relative_path)
		if not exists(absolute_path):
			raise ValueError(f"Modpack directory {relative_path} does not exist!")
		return MakeAssetData(
			relative_path=relative_path,
			output_path=join("mod_assets", relative_path),
			output_filename=basename(absolute_path) if not isdir(absolute_path) else None
		)
