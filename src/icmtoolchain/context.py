import os
import threading
from copy import deepcopy
from os.path import abspath, dirname, isfile, join
from typing import TYPE_CHECKING, Iterable, Optional

from .config import Config, FileConfig

if TYPE_CHECKING:
	from .language import MakeDataConfig

def find_config_directory(path: str, filename: str) -> Optional[str]:
	working_directory = abspath(path)
	# When searching for config ignore root directory and iterate
	# through parent ones until resolution or nothing.
	while working_directory and working_directory != dirname(working_directory):
		config_path = join(working_directory, filename)
		if isfile(config_path):
			return config_path
		working_directory = dirname(working_directory)

def find_project_config(path: str) -> Optional['MakeDataConfig']:
	from .language import MakeDataConfig
	working_directory = abspath(path)
	# When searching for config ignore root directory and iterate
	# through parent ones until resolution or nothing.
	while working_directory and working_directory != dirname(working_directory):
		config = MakeDataConfig.of(working_directory)
		if config:
			return config
		working_directory = dirname(working_directory)

def iterate_config_directories(path: str, max_depth: int = 5) -> Iterable['MakeDataConfig']:
	from .language import MakeDataConfig
	path = abspath(path)
	for dirpath, dirnames, filenames in os.walk(path):
		if max_depth >= 0 and dirpath.count(os.sep, len(path) + 1) > max_depth:
			break

		for relative_directory in dirnames:
			working_directory = join(dirpath, relative_directory)
			config = MakeDataConfig.of(working_directory)
			if config:
				yield config

def get_current_directory() -> str:
	if "project" in PROPERTIES:
		relative_path = PROPERTIES.get_value_unsafe("project")
		project_path = abspath(relative_path)
		if isfile(project_path):
			return dirname(project_path)
		return project_path
	return os.getcwd()

class Globals(threading.local):
	@property
	def ADB_COMMAND(self):
		if not hasattr(self, "adb_command"):
			from .device_setup import get_adb_command
			self.adb_command = get_adb_command()
		return self.adb_command

	@property
	def BUILD_STORAGE(self):
		if not hasattr(self, "build_storage"):
			from .hash_storage import HashStorage
			self.build_storage = HashStorage(self.MAKE_CONFIG.get_build_path(".buildrc"), \
				    self.MAKE_CONFIG.get_value("development.comparingMode", "content"))
		return self.build_storage

	@property
	def OUTPUT_STORAGE(self):
		if not hasattr(self, "output_storage"):
			from .hash_storage import HashStorage
			self.output_storage = HashStorage(self.MAKE_CONFIG.get_build_path(".outputrc"), \
				     self.MAKE_CONFIG.get_value("development.comparingMode", "content"))
		return self.output_storage

	@property
	def LINKED_RESOURCE_STORAGE(self):
		if not hasattr(self, "linked_resource_storage"):
			from .mod_structure import LinkedResourceStorage
			self.linked_resource_storage = LinkedResourceStorage(self.MAKE_CONFIG.get_build_path(".contents"))
		return self.linked_resource_storage

	@property
	def TOOLCHAIN_CONFIG(self):
		if not hasattr(self, "toolchain_config"):
			from .output_directory import get_config_directory
			toolchain_config_path = join(get_config_directory(), "toolchain.json")
			toolchain_config = FileConfig(toolchain_config_path)
			workspace_config_path = find_config_directory(get_current_directory(), "toolchain.json")
			from .utils import ensure_not_whitespace
			if workspace_config_path and ensure_not_whitespace(workspace_config_path):
				workspace_config = FileConfig(workspace_config_path, defaults=toolchain_config, raise_non_existing=True)
				self.toolchain_config = workspace_config
			else:
				self.toolchain_config = toolchain_config
			if hasattr(self, "make_config"):
				self.MAKE_CONFIG.defaults = self.toolchain_config
		return self.toolchain_config

	@property
	def MAKE_CONFIG(self):
		if not hasattr(self, "make_config"):
			make_config = find_project_config(get_current_directory())
			if make_config:
				self.make_config = make_config
		if not hasattr(self, "make_config"):
			from .errors import abort
			for directory in iterate_config_directories(get_current_directory()):
				abort("This directory is not a project per se, but perhaps you would like to create a workspace based on it? Unfortunately, this feature is not yet supported.")
			abort("Not found any opened project, try running this command in project directory.")
		return self.make_config

	@property
	def PREFERRED_CONFIG(self):
		if hasattr(self, "make_config"):
			return self.MAKE_CONFIG
		make_config = find_project_config(get_current_directory())
		if make_config:
			self.make_config = make_config
			return self.MAKE_CONFIG
		return self.TOOLCHAIN_CONFIG

	@property
	def PROJECT_STRUCTURE(self):
		if not hasattr(self, "project_structure"):
			from .project_structure import BuildConfigStructure
			output_directory = self.MAKE_CONFIG.get_value("outputDirectory", "output")
			self.project_structure = BuildConfigStructure.resolve_strategy(
				project_directory=self.MAKE_CONFIG.directory,
				output_directory=GLOBALS.MAKE_CONFIG.get_path(output_directory),
				make_config=self.MAKE_CONFIG
			)
		return self.project_structure

	@property
	def TSCONFIG_DEPENDENTS(self):
		if not hasattr(self, "tsconfig_dependents"):
			from .tsconfig import TSCONFIG_DEPENDENTS
			tsconfig = deepcopy(TSCONFIG_DEPENDENTS)
			for key in self.TSCONFIG_TOOLCHAIN:
				if key in tsconfig:
					del tsconfig[key]
			self.tsconfig_dependents = tsconfig
		return self.tsconfig_dependents

	@property
	def TSCONFIG_TOOLCHAIN(self):
		if not hasattr(self, "tsconfig_toolchain"):
			from .tsconfig import TSCONFIG_TOOLCHAIN
			tsconfig = deepcopy(TSCONFIG_TOOLCHAIN)
			for key, value in self.MAKE_CONFIG.obtain_config("tsconfig").items():
				if value is None:
					del tsconfig[key]
				else:
					tsconfig[key] = value
			self.tsconfig_toolchain = tsconfig
		return self.tsconfig_toolchain

	@property
	def CODE_WORKSPACE(self):
		if not hasattr(self, "code_workspace"):
			from .workspace import CodeWorkspace
			self.code_workspace = CodeWorkspace(self.TOOLCHAIN_CONFIG.get_path(self.TOOLCHAIN_CONFIG.get_value("workspaceFile", "toolchain.code-workspace")))
		return self.code_workspace

	@property
	def CODE_SETTINGS(self):
		if not hasattr(self, "code_settings"):
			from .workspace import CodeWorkspace
			self.code_settings = CodeWorkspace(self.TOOLCHAIN_CONFIG.get_relative_path(".vscode/settings.json"))
		return self.code_settings

	@property
	def TSC_COMPOSITE(self):
		if not hasattr(self, "typescript_composite"):
			from .tsconfig import CompositeProject
			self.typescript_composite = CompositeProject(".toolchain.tsconfig.json")
		return self.typescript_composite

	@property
	def PARAMETER_SIGNATURE(self):
		if not hasattr(self, "parameter_signature"):
			import inspect
			parameters = [
				inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=annotation) for name, annotation in PARAMETERS.items()
			]
			parameters.append(inspect.Parameter("kwargs", inspect.Parameter.VAR_KEYWORD))
			self.parameter_signature = inspect.Signature(parameters, return_annotation=int)
		return self.parameter_signature

	def is_project_available(self, which_project: Optional[str] = None):
		from .language import MakeDataConfig
		if not isinstance(self.PREFERRED_CONFIG, MakeDataConfig):
			return False
		return which_project is None or which_project == self.MAKE_CONFIG.current_project

	def shutdown(self):
		self.shutdown_project()
		if hasattr(self, "code_settings"):
			del self.code_settings
		if hasattr(self, "code_workspace"):
			del self.code_workspace
		if hasattr(self, "parameter_signature"):
			del self.parameter_signature
		if hasattr(self, "toolchain_config"):
			del self.toolchain_config

	def shutdown_project(self):
		if hasattr(self, "adb_command"):
			del self.adb_command
		if hasattr(self, "build_storage"):
			del self.build_storage
		if hasattr(self, "make_config"):
			del self.make_config
		if hasattr(self, "project_structure"):
			del self.project_structure
		if hasattr(self, "output_storage"):
			del self.output_storage
		if hasattr(self, "linked_resource_storage"):
			del self.linked_resource_storage
		if hasattr(self, "tsconfig_dependents"):
			del self.tsconfig_dependents
		if hasattr(self, "tsconfig_toolchain"):
			del self.tsconfig_toolchain
		if hasattr(self, "typescript_composite"):
			del self.typescript_composite

GLOBALS = Globals()

PARAMETERS = {
	"release": bool
}

PROPERTIES = Config()
