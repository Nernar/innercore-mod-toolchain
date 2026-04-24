from .build_config import BuildConfig
from .context import (GLOBALS, PARAMETERS, PROPERTIES, find_config_directory,
                      find_project_config, get_current_directory,
                      iterate_config_directories)
from .language import MakeDataConfig
from .make_config import MakeConfig
from .modpack_config import ModpackConfig

MakeDataConfig.register("make.json", MakeConfig)
MakeDataConfig.register("modpack.json", ModpackConfig)
MakeDataConfig.register("build.config", BuildConfig)
