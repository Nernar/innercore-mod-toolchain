from copy import deepcopy
from os.path import isdir
from typing import Callable, Dict, Optional

from .config import Config
from .output_directory import expand_paths
from .shell import warn
from .utils import RuntimeCodeError


def get_language_directories(compile_type: str, language_config: Config, properties_merger: Optional[Callable] = None) -> Dict[str, Config]:
	from . import GLOBALS

	directories = language_config.obtain_list("directories")
	if not any(directories):
		# Obtain directories from deprecated `compile` property.
		directories = list(filter(
			lambda source: isinstance(source, Config) and compile_type == source.get_value("type"),
			GLOBALS.MAKE_CONFIG.obtain_list("compile")
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

		for flattened_directory in expand_paths(GLOBALS.MAKE_CONFIG.get_relative_path(directory)):
			absolute_directory = GLOBALS.MAKE_CONFIG.get_path(flattened_directory)
			if not isdir(absolute_directory):
				warn(f"* Skipped non-existing {compile_type} directory {directory!r}!")
				continue
			if absolute_directory in configurables:
				warn(f"* Duplicated {compile_type} directory {directory!r}, overriding existing properties...")

			if properties_merger:
				config = properties_merger(config, language_config)
			else:
				temporary_config = Config(deepcopy(language_config.as_json()))
				if config:
					temporary_config.merge_config(config, exclusive_lists=True)
				config = temporary_config
			config.set_value("directory", GLOBALS.MAKE_CONFIG.get_path_to_config(flattened_directory))
			configurables[absolute_directory] = config

	return configurables
