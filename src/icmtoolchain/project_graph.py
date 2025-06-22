import json
import os
from abc import ABCMeta, abstractmethod
from functools import cmp_to_key
from itertools import chain
from os.path import abspath, basename, exists, isdir, isfile, join
from typing import (Any, Callable, Dict, Final, List, MutableSequence,
                    MutableSet, Optional, Tuple, Type, Union)

from . import GLOBALS
from .config import Config
from .language import MakeDataConfig
from .shell import abort, attention, confirm_prompt, pretty_print
from .utils import ensure_not_whitespace, remove_tree

AVAILABLE_ARTIFACTS: Dict[Union[type, Callable[[Any], bool]], Union[Callable[[Any], 'Artifact'], Type['Artifact']]] = {}

class Artifact(metaclass=ABCMeta):
	def __init__(self, description: Any) -> None:
		self.description = description

	@abstractmethod
	def fetch(self) -> None:
		...

	@abstractmethod
	def as_project(self) -> Optional['MakeDataConfig']:
		...

	@staticmethod
	def register(criteria: Union[type, Callable[[Any], bool]], data: Union[Callable[[Any], 'Artifact'], Type['Artifact']]) -> None:
		"""Here you can match right artifact to different types of dependencies.

		Args:
			criteria (Union[str, Callable[[str], bool]]): filter artifact types by filename or deeper callable inspection
			data (type[Artifact]): type to be created, which will become a artifact with data

		Raises:
			ValueError: if this criteria has already been registered earlier
		"""
		if criteria in AVAILABLE_ARTIFACTS:
			raise ValueError(f"Data criteria {criteria} already occupied by {AVAILABLE_ARTIFACTS[criteria]}!")
		AVAILABLE_ARTIFACTS[criteria] = data

	@staticmethod
	def of(description: Any) -> Optional['Artifact']:
		for criteria, artifact_type in AVAILABLE_ARTIFACTS.items():
			if isinstance(criteria, type):
				if not isinstance(description, criteria):
					continue
			elif callable(criteria):
				if not criteria(description):
					continue
			else:
				continue
			return artifact_type(description)

class ModBrowserArtifact(Artifact):
	description: int

	def __init__(self, remote_id: int) -> None:
		super().__init__(remote_id)

	def fetch(self) -> None:
		pass

	def as_project(self) -> Optional['MakeDataConfig']:
		raise NotImplementedError()

Artifact.register(int, ModBrowserArtifact)
Artifact.register(lambda description: isinstance(description, dict) and "projectId" in description, lambda description: ModBrowserArtifact(description["projectId"]))

class RepositoryArtifact(Artifact):
	description: str

	def __init__(self, remote_url: str) -> None:
		super().__init__(remote_url)

	def fetch(self) -> None:
		pass

	def as_project(self) -> Optional['MakeDataConfig']:
		raise NotImplementedError()

Artifact.register(lambda description: isinstance(description, str) and "://" in description, RepositoryArtifact)
Artifact.register(lambda description: isinstance(description, dict) and "url" in description, lambda description: RepositoryArtifact(description["url"]))

class ProjectEdge:
	dependencies: MutableSequence['ProjectEdge']
	references: MutableSequence['ProjectEdge']
	artifact: Optional[Artifact] = None

	def __init__(self, project: Union[MakeDataConfig, Artifact]):
		self.project = project
		if isinstance(project, Artifact):
			self.artifact = project
		self.dependencies = []
		self.references = []

	def __repr__(self) -> str:
		return f"ProjectEdge(project={self.project}, dependencies=({', '.join(str(edge.project) for edge in self.dependencies)}), references=({', '.join(str(edge.project) for edge in self.references)}))"

	def __str__(self) -> str:
		return f"Project {self.project} ({len(self.dependencies)} dependencies)"

class ProjectGraph(Dict[Union[MakeDataConfig, Artifact], ProjectEdge]):
	def __init__(self, project: MakeDataConfig) -> None:
		self.project = project
		self.obtain_edge(project)

	@property
	def root(self) -> ProjectEdge:
		return self.obtain_edge(self.project)

	def obtain_edge(self, config: Union[MakeDataConfig, Artifact]) -> ProjectEdge:
		if not config in self:
			self[config] = ProjectEdge(config)
		return self[config]

	def obtain_project(self, edge: ProjectEdge) -> Union[MakeDataConfig, Artifact]:
		for config, subedge in self.items():
			if edge == subedge:
				return config
		raise ValueError(f"ProjectGraph#project_of: Unresolved edge {edge.project}!")

	def depend_on(self, edge: ProjectEdge, dependency: ProjectEdge) -> None:
		if not dependency in edge.dependencies:
			edge.dependencies.append(dependency)
		if not edge in dependency.references:
			dependency.references.append(edge)

	def undepend_on(self, edge: ProjectEdge, dependency: ProjectEdge, keep_unused: bool = False) -> None:
		removed_something = False
		if edge in dependency.references:
			dependency.references.remove(edge)
			removed_something = True
		if dependency in edge.dependencies:
			edge.dependencies.remove(dependency)
			removed_something = True
		if removed_something and not keep_unused:
			self.remove_unused_edges()

	def remove_edge(self, edge: ProjectEdge, keep_unused: bool = False) -> None:
		edge_key = None
		for config, subedge in self.items():
			if edge == subedge:
				edge_key = config
				break
		if edge_key:
			del self[edge_key]
		for config, subedge in self.items():
			if edge in subedge.dependencies:
				subedge.dependencies.remove(edge)
			if edge in subedge.references:
				subedge.references.remove(edge)
		if not keep_unused:
			self.remove_unused_edges()

	def remove_unused_edges(self, edge: Optional[ProjectEdge] = None) -> MutableSet[ProjectEdge]:
		removed_edges = set()
		dependencies = self.traverse_referenced_nodes(edge)
		for config, node in list(self.items()):
			if node not in dependencies:
				removed_edges.add(node)
				del self[config]
		return removed_edges

	def collect_dependencies(self, config: MakeDataConfig, parent: Optional[ProjectEdge] = None) -> None:
		if not parent:
			parent = self.root
		for dependency in config.iterate_dependencies():
			child = self.obtain_edge(dependency)
			if isinstance(dependency, MakeDataConfig):
				self.collect_dependencies(dependency, child)
			self.depend_on(parent, child)

	def resolve_dependencies(self, edge: Optional[ProjectEdge] = None, keep_unused: bool = False, traversed_references: Optional[MutableSet[ProjectEdge]] = None) -> MutableSet[ProjectEdge]:
		if not edge:
			edge = self.root
		edge_unresolved_artifacts: MutableSet[ProjectEdge] = set()
		unresolved_artifacts: MutableSet[ProjectEdge] = set()
		if not traversed_references:
			traversed_references = set()
		traversed_references.add(edge)
		for dependency in edge.dependencies:
			if dependency in traversed_references:
				# Unresolved dependencies will be shown and collected later,
				# we just need to avoid recursion.
				continue
			if not isinstance(dependency.project, MakeDataConfig):
				assert dependency.artifact
				dependency.artifact.fetch()
				project = dependency.artifact.as_project()
				# Ignoring unresolved projects intentionally, otherwise artifact
				# itself can throw an error if resolving required.
				if not project:
					edge_unresolved_artifacts.add(dependency)
					traversed_references.add(dependency)
					continue
				dependency.project = project
				self.collect_dependencies(project, dependency)
			dependency_unresolved_artifacts = self.resolve_dependencies(dependency, keep_unused=keep_unused, traversed_references=traversed_references)
			unresolved_artifacts.update(dependency_unresolved_artifacts)
		unresolved_artifacts.update(edge_unresolved_artifacts)
		if not keep_unused:
			for artifact_edge in edge_unresolved_artifacts:
				self.remove_edge(artifact_edge)
		return unresolved_artifacts

	def find_dependencies(self, dependency: ProjectEdge) -> MutableSequence[ProjectEdge]:
		dependencies = []
		for config, node in self.items():
			if dependency in node.dependencies:
				dependencies.append(node)
		return dependencies

	def find_references(self, reference: ProjectEdge) -> MutableSequence[ProjectEdge]:
		references = []
		for config, node in self.items():
			if reference in node.references:
				references.append(node)
		return references

	def traverse_referenced_nodes(self, edge: Optional[ProjectEdge] = None, collected_edges: Optional[MutableSet[ProjectEdge]] = None) -> MutableSet[ProjectEdge]:
		if not edge:
			edge = self.root
		if not collected_edges:
			collected_edges = set()
		collected_edges.add(edge)
		for reference in chain(edge.dependencies, edge.references):
			if reference in collected_edges:
				continue
			self.traverse_referenced_nodes(reference, collected_edges=collected_edges)
		return collected_edges
	
	def traverse_priority_dependencies(self, edge: Optional[ProjectEdge] = None) -> MutableSequence[ProjectEdge]:
		if not edge:
			edge = self.root
		def compare_dependencies(a: ProjectEdge, b: ProjectEdge) -> int:
			# Number of dependencies is prioritized, fewer is better.
			da = len(a.dependencies)
			db = len(b.dependencies)
			if da < db:
				return -1
			elif da > db:
				return 1
			# Now references, more is better.
			ra = len(a.references)
			rb = len(b.references)
			if ra > rb:
				return -1
			elif ra < rb:
				return 1
			return 0
		return sorted(self.values(), key=cmp_to_key(compare_dependencies))

	def traverse_dependencies(self, edge: Optional[ProjectEdge] = None) -> MutableSequence[ProjectEdge]:
		dependencies = self.traverse_priority_dependencies(edge)
		traversed_dependencies: MutableSequence[ProjectEdge] = []
		unresolved_dependencies: MutableSequence[ProjectEdge] = []
		index = 0
		while index < len(dependencies):
			reference = dependencies[index]
			# All previously listed dependencies must satisfy reference.
			unresolved = False
			for dependency in reference.dependencies:
				if not dependency in traversed_dependencies:
					unresolved = True
					break
			if unresolved:
				unresolved_dependencies.append(reference)
				dependencies.remove(reference)
				continue
			traversed_dependencies.append(reference)
			# Now that dependency is resolved, we can make sure that there
			# are references for following iterations.
			for dependency in reversed(unresolved_dependencies[:]):
				# If there is no reference, dependency is still unresolved.
				if reference not in dependency.dependencies:
					continue
				unresolved = False
				for requirement in dependency.dependencies:
					if requirement not in traversed_dependencies:
						unresolved = True
						break
				if not unresolved:
					dependencies.insert(index + 1, dependency)
					unresolved_dependencies.remove(dependency)
			index += 1
		return dependencies	

	def find_circular_reference(self, node: Optional[ProjectEdge] = None, visited: Optional[MutableSequence[ProjectEdge]] = None) -> Optional[Tuple[ProjectEdge, ProjectEdge]]:
		if not node:
			node = self.root
		if not visited:
			visited = list()
		if node in visited:
			return (visited[-1], node)
		visited.append(node)
		for dependency in node.dependencies:
			cross_references = self.find_circular_reference(dependency, visited)
			if cross_references:
				return cross_references
		visited.remove(node)

class ProjectManager:
	projects: Final[List[str]]
	templates: Final[List[str]]

	def __init__(self) -> None:
		self.projects = list()
		self.templates = list()
		locations = GLOBALS.PREFERRED_CONFIG.obtain_list("projectLocations")
		for location in locations[:]:
			path = GLOBALS.TOOLCHAIN_CONFIG.get_path(location)
			if not exists(path) or not isdir(path):
				attention(f"Not found project location {location}!")
				continue

			for entry in os.listdir(path):
				make_path = join(path, entry, "make.json")
				if exists(make_path) and isfile(make_path):
					self.projects.append(join(location, entry))
				template_path = join(path, entry, "template.json")
				if exists(template_path) and isfile(template_path):
					self.templates.append(join(location, entry))

	def create_project(self, template: str, folder: str, name: Optional[str] = None, author: Optional[str] = None, version: Optional[str] = None, description: Optional[str] = None, clientOnly: bool = False)-> int:
		location = GLOBALS.TOOLCHAIN_CONFIG.get_relative_path(folder)
		if exists(location):
			abort(f"Folder {folder!r} already exists!")
		template_path = GLOBALS.TOOLCHAIN_CONFIG.get_path(template)
		if not exists(template_path):
			abort(f"Not found {template!r} template, nothing to do.")
		template_make_path = GLOBALS.TOOLCHAIN_CONFIG.get_path(join(template, "template.json"))
		if not isfile(template_make_path):
			abort(f"Not found 'template.json' in template {template!r}, nothing to do.")

		with open(template_make_path, "r", encoding="utf-8") as make_file:
			template_obj = json.loads(make_file.read())

		if not "info" in template_obj:
			template_obj["info"] = dict()
		template_info = template_obj["info"]
		template_info["name"] = ensure_not_whitespace(name, ensure_not_whitespace(
			template_info["name"] if "name" in template_info else None, "Mod"
		))
		template_info["author"] = ensure_not_whitespace(author, ensure_not_whitespace(
			template_info["author"] if "author" in template_info else None, "ICMods"
		))
		template_info["version"] = ensure_not_whitespace(version, ensure_not_whitespace(
			template_info["version"] if "version" in template_info else None, "1.0"
		))
		template_info["description"] = description or ensure_not_whitespace(
			template_info["description"] if "description" in template_info else None, "Describe your creation just in a few words."
		)
		template_info["clientOnly"] = clientOnly if clientOnly is not None else \
			template_info["clientOnly"] if "clientOnly" in template_info else False

		os.makedirs(location)
		from .package import setup_project
		setup_project(template_obj, template_path, location)

		make_path = join(location, "make.json")
		with open(make_path, "w", encoding="utf-8") as make_file:
			make_file.write(json.dumps(template_obj, indent="\t", ensure_ascii=False) + "\n")

		if GLOBALS.CODE_WORKSPACE.available():
			location = GLOBALS.CODE_WORKSPACE.get_toolchain_path(folder).replace("\\", "/")
			if not any(filter(lambda folder: isinstance(folder, Config) and location == folder.get_value("path"), GLOBALS.CODE_WORKSPACE.obtain_list("folders"))):
				self.append_workspace_folder(folder, template_info["name"])

		if GLOBALS.CODE_SETTINGS.available():
			exclude = GLOBALS.CODE_SETTINGS.obtain_config("files.exclude", implace_fallback=True)
			if not folder.startswith("../"):
				exclude[folder] = True
				GLOBALS.CODE_SETTINGS.save_as_file()

		self.projects.append(folder)
		return self.how_much() - 1

	def remove_project(self, index: Optional[int] = None, folder: Optional[str] = None) -> None:
		if len(self.projects) == 0:
			abort("Not found any project to remove.")

		index, folder = self.get_folder(index, folder)

		if GLOBALS.is_project_available(which_project=folder):
			self.unselect_project(silent=True)

		if GLOBALS.CODE_WORKSPACE.available():
			location = GLOBALS.CODE_WORKSPACE.get_toolchain_path(folder).replace("\\", "/")
			workspace_directories = GLOBALS.CODE_WORKSPACE.obtain_list("folders")
			requires_saving = False
			for directory in filter(lambda folder: isinstance(folder, Config) and location == folder.get_value("path"), workspace_directories[:]):
				workspace_directories.remove(directory)
				requires_saving = True
			if requires_saving:
				GLOBALS.CODE_WORKSPACE.save_as_file()

		if GLOBALS.CODE_SETTINGS.available():
			exclude = GLOBALS.CODE_SETTINGS.obtain_config("files.exclude")
			if folder in exclude:
				del exclude[folder]
				GLOBALS.CODE_SETTINGS.save_as_file()

		remove_tree(GLOBALS.TOOLCHAIN_CONFIG.get_path(folder))
		if index != -1:
			del self.projects[index]

	def append_workspace_folder(self, folder: str, name: Optional[object] = "Mod") -> None:
		if GLOBALS.CODE_WORKSPACE.available():
			folders = GLOBALS.CODE_WORKSPACE.obtain_list("folders", implace_fallback=True)
			if len(folders) == 0:
				folders.append({
					"path": GLOBALS.CODE_WORKSPACE.get_toolchain_path().replace("\\", "/"),
					"name": "Inner Core Mod Toolchain"
				})
			folders.append({
				"path": GLOBALS.CODE_WORKSPACE.get_toolchain_path(folder).replace("\\", "/"),
				"name": str(name)
			})
			GLOBALS.CODE_WORKSPACE.save_as_file()

	def select_project_folder(self, folder: Optional[str] = None) -> None:
		if GLOBALS.is_project_available(which_project=folder):
			return
		from . import PROPERTIES
		PROPERTIES.set_value("project", folder)
		GLOBALS.shutdown_project()

	def select_project(self, index: Optional[int] = None, folder: Optional[str] = None) -> None:
		index, folder = self.get_folder(index, folder)

		if folder and GLOBALS.CODE_WORKSPACE.available():
			location = GLOBALS.CODE_WORKSPACE.get_toolchain_path(folder).replace("\\", "/")
			if not any(filter(lambda folder: isinstance(folder, Config) and location == folder.get_value("path"), GLOBALS.CODE_WORKSPACE.obtain_list("folders"))):
				make_path = GLOBALS.TOOLCHAIN_CONFIG.get_path(join(folder, "make.json"))
				if not isfile(make_path):
					abort(f"Not found 'make.json' in project {folder!r}, nothing to do.")
				with open(make_path, "r", encoding="utf-8") as make_file:
					make_obj = json.loads(make_file.read())
				self.append_workspace_folder(folder, self.resolve_mod_name(folder, make_obj))

		if folder and GLOBALS.CODE_SETTINGS.available():
			exclude = GLOBALS.CODE_SETTINGS.obtain_config("files.exclude")
			if GLOBALS.is_project_available():
				if not GLOBALS.MAKE_CONFIG.current_project.startswith("../") and not exists(abspath(GLOBALS.MAKE_CONFIG.current_project)):
					exclude[GLOBALS.MAKE_CONFIG.current_project] = True
			if not folder.startswith("../"):
				exclude[folder] = False
			GLOBALS.CODE_SETTINGS.save_as_file()

		self.select_project_folder(folder)
		pretty_print(f"Project {folder!r} selected.")

	def unselect_project(self, *, silent: bool = False):
		self.select_project_folder()
		if not silent:
			pretty_print(f"Project unselected.")

	def resolve_mod_name(self, path: str, make_obj: Optional[Dict[Any, Any]] = None) -> str:
		if not make_obj:
			try:
				make_path = GLOBALS.TOOLCHAIN_CONFIG.get_path(join(path, "make.json"))
				if isfile(make_path):
					with open(make_path, "r", encoding="utf-8") as make_file:
						make_obj = json.loads(make_file.read())
			except BaseException:
				pass
		return make_obj["info"]["name"] if make_obj and "info" in make_obj and "name" in make_obj["info"] else basename(path)

	def get_shortcut(self, path: str, make_obj: Optional[Dict[Any, Any]] = None) -> str:
		if len(path) == 0:
			return basename(GLOBALS.TOOLCHAIN_CONFIG.directory)
		return self.resolve_mod_name(path, make_obj) + " (" + path + ")"

	def get_folder(self, index: Optional[int] = None, folder: Optional[str] = None) -> Tuple[int, str]:
		if index is None:
			if folder is None:
				raise ValueError("Folder index must be specified!")
			else:
				index = next((i for i, x in enumerate(self.projects)
					if x.lower() == folder.lower()
				), -1)
		if index != -1:
			folder = self.projects[index]
		if folder is None:
			raise ValueError("Existing folder or indexable project should be passed to selector!")
		return index, folder

	def how_much(self) -> int:
		return len(self.projects)

	def require_selection(self, prompt: Optional[str] = None, prompt_when_single: Optional[str] = None, *dont_want_anymore: str) -> Optional[str]:
		from .package import select_project
		if self.how_much() == 1:
			itwillbe = self.projects[0]
			if not prompt_when_single:
				return itwillbe
			else:
				if not confirm_prompt(prompt_when_single.format(self.get_shortcut(itwillbe)), True):
					return None
				return itwillbe
		return select_project(self.projects, prompt, GLOBALS.MAKE_CONFIG.current_project if GLOBALS.is_project_available() else None, *dont_want_anymore)
