import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from os.path import abspath, isfile, join
from typing import Any, Dict, List, Optional

from .config import FileConfig
from .language import MakeDataConfig
from .utils import ensure_directory, remove_tree


@dataclass
class BuildTargetEntry:
	name: str
	relative_path: str
	exclude: bool = False
	declare: Dict[str, Any] = field(default_factory=dict)
	declare_default: Dict[str, Any] = field(default_factory=dict)

class BuildTarget:
	def __init__(self, relative_directory: str, output_directory: str, export_group: str = ""):
		self.relative_directory = relative_directory
		self.output_directory = output_directory
		self.export_group = export_group
		self.entries: List[BuildTargetEntry] = []

	def declare(self, name: str, relative_path: str, exclude: bool = False, declare: Optional[Dict] = None, declare_default: Optional[Dict] = None) -> BuildTargetEntry:
		if "{}" not in name:
			name += "{}"

		existing_names = { entry.name for entry in self.entries }
		index = 0
		formatted_name = name.format("")
		while formatted_name in existing_names:
			formatted_name = name.format(index)
			index += 1

		entry = BuildTargetEntry(
			name=formatted_name,
			relative_path=join(relative_path, formatted_name).replace("\\", "/"),
			exclude=exclude,
			declare=declare or {},
			declare_default=declare_default or {}
		)
		self.entries.append(entry)
		return entry

	def cleanup(self, clear_output: bool = True) -> None:
		ensure_directory(self.output_directory)

	def export(self, default_overrides: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
		result = []
		for entry in self.entries:
			if entry.exclude:
				continue

			result.append({
				"path": entry.relative_path,
				**entry.declare
			})

			if default_overrides is not None and entry.declare_default:
				default_overrides.update(entry.declare_default)
		return result

class IsolatedTarget(BuildTarget):
	def cleanup(self, clear_output: bool = True) -> None:
		self.entries.clear()
		if clear_output:
			remove_tree(self.output_directory)
		super().cleanup(clear_output=clear_output)

class InplaceTarget(BuildTarget):
	def cleanup(self, clear_output: bool = True) -> None:
		if clear_output:
			for entry in self.entries:
				self.cleanup_entry(entry)
		self.entries.clear()
		super().cleanup(clear_output=clear_output)

	def cleanup_entry(self, entry: BuildTargetEntry) -> None:
		file_path = join(self.output_directory, entry.name)
		if isfile(file_path):
			os.remove(file_path)

class ScriptInplaceTarget(InplaceTarget):
	def cleanup_entry(self, entry: BuildTargetEntry) -> None:
		file_path = join(self.output_directory, entry.name)
		if file_path.endswith(".js") and isfile(file_path):
			os.remove(file_path)

class JavaInplaceTarget(InplaceTarget):
	def cleanup_entry(self, entry: BuildTargetEntry) -> None:
		dex_path = join(self.output_directory, "classes.dex")
		if isfile(dex_path):
			os.remove(dex_path)

class ProjectStructure(ABC):
	def __init__(self, output_directory: str):
		self.directory = output_directory
		self.targets: Dict[str, BuildTarget] = {}
		self.setup_targets()

	def register(self, keyword: str, target: BuildTarget) -> BuildTarget:
		if keyword in self.targets:
			raise ValueError(f"Project target {keyword!r} already used within structure!")
		self.targets[keyword] = target
		return target

	def get(self, keyword: str) -> BuildTarget:
		if not keyword in self.targets:
			raise KeyError(f"Project target {keyword!r} cannot be satisfied!")
		return self.targets[keyword]

	@abstractmethod
	def setup_targets(self) -> None: ...

	@abstractmethod
	def generate_config(self) -> None: ...

	def export_group(self, group: str, default_overrides: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
		result = []
		for target in self.targets.values():
			if target.export_group == group:
				result.extend(target.export(default_overrides))
		return result

	def cleanup(self, clear_output: bool = True) -> None:
		for target in self.targets.values():
			target.cleanup(clear_output)

class BuildConfigStructure(ProjectStructure, ABC):
	def __init__(self, output_directory: str, make_config: MakeDataConfig):
		self.make_config = make_config
		super().__init__(output_directory)

	@classmethod
	def resolve_strategy(cls, project_directory: str, output_directory: str, make_config: MakeDataConfig) -> ProjectStructure:
		project_path = abspath(project_directory)
		output_path = abspath(output_directory)
		default_output_path = abspath(join(project_directory, "output"))

		if project_path == output_path:
			return InplaceBuildConfigStructure(output_path, make_config)

		if output_path == default_output_path:
			return IsolatedBuildConfigStructure(output_path, make_config)

		config_path = join(output_path, "build.config")
		if isfile(config_path):
			return InplaceBuildConfigStructure(output_path, make_config)

		return IsolatedBuildConfigStructure(output_path, make_config)

	def merge_target_group(self, config: Dict, group_name: str, generated_items: List[Dict]) -> None:
		existing_items = config.get(group_name, [])
		if not isinstance(existing_items, list):
			existing_items = []

		existing_paths = { item.get("path") for item in existing_items if isinstance(item, dict) and "path" in item }

		for generated_item in generated_items:
			if generated_item["path"] not in existing_paths:
				existing_items.append(generated_item)

		config[group_name] = existing_items

	def generate_config(self) -> None:
		config_path = join(self.directory, "build.config")
		config = FileConfig(config_path)

		if not "defaultConfig" in config:
			config.set_value("defaultConfig", {
				"readme": "this build config is generated automatically by icmtoolchain",
				"buildType": "develop"
			})
			if not "buildDirs" in config:
				config.set_value("buildDirs", [])
		default_config = config.get_value("defaultConfig")

		self.merge_target_group(config, "compile", self.export_group("compile", default_config))
		self.merge_target_group(config, "resources", self.export_group("resources"))
		self.merge_target_group(config, "javaDirs", self.export_group("javaDirs"))
		self.merge_target_group(config, "nativeDirs", self.export_group("nativeDirs"))

		config.save_as_file(indent=" " * 2)

class IsolatedBuildConfigStructure(BuildConfigStructure):
	def setup_targets(self) -> None:
		source_path = self.make_config.get_value("target.source", "source")
		self.register("scripts", IsolatedTarget(
			relative_directory=source_path,
			output_directory=join(self.directory, source_path),
			export_group="compile"
		))

		# TODO

class InplaceBuildConfigStructure(BuildConfigStructure):
	def setup_targets(self) -> None:
		source_path = self.make_config.get_value("target.source", "source")
		self.register("scripts", ScriptInplaceTarget(
			relative_directory=source_path,
			output_directory=join(self.directory, source_path),
			export_group="compile"
		))

		# TODO
