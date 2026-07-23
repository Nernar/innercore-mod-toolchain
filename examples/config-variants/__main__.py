from itertools import tee
from os.path import dirname, join
from time import time
from typing import Iterable, Union

from icmtoolchain import GLOBALS, iterate_config_directories
from icmtoolchain.cli import execute_task
from icmtoolchain.config import FileConfig
from icmtoolchain.language import MakeAssetData, MakeDataConfig
from icmtoolchain.parser import parse_arguments
from icmtoolchain.project_graph import Artifact, ProjectGraph
from icmtoolchain.logger import attention, success
from icmtoolchain.task import TASKS
import icmtoolchain.builtin_tasks

startup_millis = time()
build_command = "--release ensureProjectExists clearOutput --force buildScripts compileNative compileJava buildResources buildInfo buildPackage"
targets = parse_arguments(list(build_command.split(" ")), TASKS, lambda name, target, callables: attention(f"No such task: {name}."))

class IsolatedWorkspace(MakeDataConfig):
	def __init__(self, path: str, projects: Iterable[MakeDataConfig]):
		workspace_config = FileConfig(join(path, "workspace.json"))
		super().__init__(GLOBALS.TOOLCHAIN_CONFIG.path, workspace_config)
		self.dependencies = projects

	def obtain_project_data(self) -> None:
		return None

	def iterate_dependencies(self) -> Iterable[Union[MakeDataConfig, Artifact]]:
		return self.dependencies

	def iterate_assets(self) -> Iterable[MakeAssetData]:
		return []

workspace_path = dirname(__file__)
dependencies = iterate_config_directories(workspace_path)
workspace = IsolatedWorkspace(workspace_path, dependencies)
graph = ProjectGraph(workspace)
graph.collect_dependencies(workspace)
graph.resolve_dependencies()

for edge in graph.traverse_dependencies():
	if isinstance(edge.project, IsolatedWorkspace):
		continue
	GLOBALS.shutdown_project()
	assert isinstance(edge.project, MakeDataConfig)
	GLOBALS.make_config = edge.project
	targets, tasks = tee(targets)
	while True:
		try:
			callable = next(tasks)
		except StopIteration:
			break
		else:
			execute_task(callable)

startup_millis = time() - startup_millis
success(f"Tasks successfully completed in {startup_millis:.2f}s!")
