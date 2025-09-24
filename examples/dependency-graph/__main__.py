from os.path import basename, dirname, join

from icmtoolchain.cli import resolve_circular_references
from icmtoolchain.config import FileConfig
from icmtoolchain.language import MakeDataConfig
from icmtoolchain.project_graph import ProjectGraph
from icmtoolchain.utils import RuntimeCodeError

RESOLVED_DEPENDENCY_ORDER = [
	"8-multi-reference",
	"4-circular-dependency",
	"7-simple-reference",
	"3-cross-reference",
	"2-circular-reference",
	"6-multi-dependency",
	"5-simple-dependency",
	"1-master-project"
]

master_project_path = join(dirname(__file__), "1-master-project")
master_project = MakeDataConfig.of(master_project_path)
if not master_project:
	raise RuntimeCodeError(1, "No such project.")
graph = ProjectGraph(master_project)
graph.collect_dependencies(master_project)
if len(graph) != len(RESOLVED_DEPENDENCY_ORDER):
	raise RuntimeCodeError(2, f"Graph dependencies length mismatch: {len(RESOLVED_DEPENDENCY_ORDER)} != {len(graph)}.")
graph.resolve_dependencies()
if not resolve_circular_references(graph):
	raise RuntimeCodeError(3, "Expected circular dependencies, but nothing was found.")
resolved_dependencies = []
for dependency in graph.traverse_dependencies():
	assert isinstance(dependency.project, FileConfig)
	resolved_dependencies.append(basename(dependency.project.directory))
if resolved_dependencies != RESOLVED_DEPENDENCY_ORDER:
	raise RuntimeCodeError(4, f"Traversed dependencies sorting mismatch: {' -> '.join(resolved_dependencies)}.")
