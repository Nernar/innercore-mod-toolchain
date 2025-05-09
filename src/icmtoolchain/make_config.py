from os.path import basename, isfile, join
from typing import Final, Optional

from .config import Config, FileConfig
from .shell import abort


class ToolchainConfig(FileConfig):
	def __init__(self, path: str, defaults: Optional[Config] = None) -> None:
		super().__init__(path, defaults=defaults)
		if not defaults and basename(path) in ("make.json", "toolchain.json"):
			self.upgrade()

	def upgrade(self) -> bool:
		changes = False
		if "global" in self:
			global_config = self.get_value("global", dict())
			for entry in global_config:
				self.set_value(entry, global_config[entry])
			self.delete_value("global")
			changes |= True
		if "make" in self:
			make_config = self.get_value("make", dict())
			if "linkNative" in make_config:
				self.set_value("linkNative", make_config["linkNative"])
			if "excludeFromRelease" in make_config:
				self.set_value("excludeFromRelease", make_config["excludeFromRelease"])
			self.delete_value("make")
			changes |= True
		if "gradle" in self:
			gradle_config = self.get_value("gradle", dict())
			java_config = self.get_value("java", dict())
			for entry in gradle_config:
				java_config.set_value(entry, gradle_config[entry])
			self.set_value("java", java_config)
			self.delete_value("gradle")
			changes |= True
		if changes:
			self.save_as_file()
		return changes

class MakeConfig(ToolchainConfig):
	defaults: ToolchainConfig
	current_project: Final[str]
	project_unique_name: Final[str]

	def __init__(self, path: str, defaults: ToolchainConfig) -> None:
		if not isfile(path):
			abort(f"Not found {basename(path)!r}, are you sure that selected project exists?")
		self.current_project = defaults.get_value("currentProject")
		super().__init__(path, defaults=defaults)
		from .output_directory import unique_folder_name
		self.project_unique_name = unique_folder_name(self.directory)

	def get_build_path(self, relative_path: str) -> str:
		return self.defaults.get_relative_path(join("build", self.project_unique_name, relative_path))
