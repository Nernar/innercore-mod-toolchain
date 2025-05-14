from functools import cmp_to_key
from os.path import basename, isfile, splitext
from typing import Iterable, Optional, override

from .config import Config, FileConfig
from .language import MakeDataConfig, MakeModData, MakeScriptData


class BuildConfig(MakeDataConfig):
	def __init__(self, path: str, defaults: FileConfig) -> None:
		super().__init__(path, defaults)

	@override
	def obtain_project_data(self) -> Optional[MakeModData]:
		mod_info_file = self.get_relative_path("mod.info")
		if isfile(mod_info_file):
			mod_info = FileConfig(mod_info_file)
			return self.obtain_mod_data(mod_info)

	@property
	@override
	def supports_scripts(self) -> bool:
		return True

	@override
	def iterate_scripts(self) -> Iterable[MakeScriptData]:
		library_directory = self.get_value("defaultConfig.libraryDir")
		if library_directory:
			yield MakeScriptData(
				relative_path=f"{library_directory}/*",
				output_path=basename(library_directory),
				type="library"
			)

		sources_list = filter(
			lambda source: isinstance(source, Config),
			self.obtain_list("compile")
		)
		for source in sorted(sources_list, key=cmp_to_key(
			lambda a, b: \
				0 if a.get_value("sourceType") == "library" and b.get_value("sourceType") == "library" \
					else -1 if a.get_value("sourceType") == "library" else 1
		)):
			yield self.obtain_script_data(source)

	def obtain_script_data(self, source: Config) -> MakeScriptData:
		relative_path = source.get_value_unsafe("path")
		from .script_build import VALID_SOURCE_TYPES
		type = source.get_value_unsafe("type")
		if type != "mod" and not type in VALID_SOURCE_TYPES:
			raise ValueError(f"Script {relative_path!r} has invalid type, it should be one of: {', '.join(VALID_SOURCE_TYPES)}!")

		build_directory = next(
			filter(lambda directory: isinstance(directory, Config) \
		  		and relative_path == directory.get_value("targetSource"), self.obtain_list("buildDirs")
			), None)
		if relative_path and build_directory:
			relative_path = build_directory.get_value("dir")
			output_path = source.get_value_unsafe("path")
		# Using template <sourceName>.<extension> -> <sourceName>, e.g. main.js -> main
		else:
			script_path = self.get_relative_path(relative_path)
			output_path = basename(script_path)
			if isfile(script_path):
				output_path = splitext(output_path)[0] + ".js"

		return MakeScriptData(
			relative_path=relative_path,
			output_path=output_path,
			type=type if type != "mod" else "main",
			source_name=source.get_value("sourceName", lambda: relative_path),
			api=source.get_value("api", lambda: source.get_value("defaultConfig.api")),
			optimization_level=source.get_value("optimizationLevel", lambda: source.get_value("defaultConfig.optimizationLevel", -1))
		)

	@property
	@override
	def supports_java(self) -> bool:
		return False

	@property
	@override
	def supports_native(self) -> bool:
		return False

	@property
	@override
	def supports_resources(self) -> bool:
		return False
