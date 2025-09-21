from os.path import basename, dirname, join

from ..cli import (resolve_circular_references,  # type: ignore
                   show_unresolved_dependencies)
from ..config import FileConfig  # type: ignore
from ..language import MakeDataConfig  # type: ignore
from ..project_graph import ProjectGraph  # type: ignore
from ..shell import failure, pretty_debug, success  # type: ignore


def pretty_print_order(graph: ProjectGraph):
	return ' -> '.join([basename(edge.project.directory) \
					 if isinstance(edge.project, FileConfig) \
						else str(edge) for edge in graph.traverse_dependencies()])

master_project_path = join(dirname(__file__), "1-master-project")
master_project = MakeDataConfig.of(master_project_path)
if master_project:
	graph = ProjectGraph(master_project)
	graph.collect_dependencies(master_project)
	success(f"Got {len(graph.values())} nodes of {basename(master_project_path)!r} dependencies")
	unresolved_artifacts = graph.resolve_dependencies()
	show_unresolved_dependencies(unresolved_artifacts)
	pretty_debug(f"Currently order (excluding affected projects): {pretty_print_order(graph)}")
	resolve_circular_references(graph)
	success(f"Order: {pretty_print_order(graph)}")
else:
	failure("No such project.")
