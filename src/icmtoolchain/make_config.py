from os.path import basename, isfile, join
from typing import Final

from .config import FileConfig
from .shell import abort


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
