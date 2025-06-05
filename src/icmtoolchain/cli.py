import sys
from itertools import tee
from typing import TYPE_CHECKING, MutableSequence, MutableSet, Optional, Union

from .language import MakeDataConfig
from .shell import pretty_print

if TYPE_CHECKING:
	from .project_manager import Artifact


def show_help():
	pretty_print("Usage: icmtoolchain [options] ... <task1> [arguments1] ...")
	pretty_print(" " * 2 + "--help: Display this message.")
	pretty_print(" " * 2 + "--list: See available tasks.")
	pretty_print("Perform commands marked with a special decorator @task.")
	pretty_print("Example: icmtoolchain selectProject --path mod1 pushEverything selectProject --path mod2 pushEverything launchApplication")

def show_available_tasks():
	from .task import TASKS
	pretty_print("All available tasks:")
	for name, task in TASKS.items():
		pretty_print(" " * 2 + name, end="")
		if task.description:
			pretty_print(": " + task.description, end="")
		pretty_print()

class ProjectEdge:
	dependencies: MutableSequence['ProjectEdge']
	references: MutableSequence['ProjectEdge']
	artifact: Optional['Artifact'] = None

	def __init__(self, project: Union[MakeDataConfig, 'Artifact']):
		self.project = project
		if not TYPE_CHECKING:
			from .project_manager import Artifact
		if isinstance(project, Artifact):
			self.artifact = project
		self.dependencies = []
		self.references = []

class ProjectGraph(dict[Union[MakeDataConfig, 'Artifact'], ProjectEdge]):
	def __init__(self, project: MakeDataConfig) -> None:
		self.project = project
		self.obtain_edge(project)

	@property
	def root(self) -> ProjectEdge:
		return self.obtain_edge(self.project)

	def obtain_edge(self, config: Union[MakeDataConfig, 'Artifact']) -> ProjectEdge:
		if not config in self:
			self[config] = ProjectEdge(config)
		return self[config]

	def obtain_project(self, edge: ProjectEdge) -> Union[MakeDataConfig, 'Artifact']:
		for config, subedge in self.items():
			if edge == subedge:
				return config
		raise ValueError(f"ProjectGraph#project_of: Unresolved edge {edge.project}!")

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

	def remove_unused_edges(self, edge: Optional[ProjectEdge] = None) -> None:
		dependencies = self.traverse_dependencies(edge)
		for config, node in list(self.items()):
			if node not in dependencies:
				del self[config]

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

	def traverse_dependencies(self, edge: Optional[ProjectEdge] = None) -> MutableSet[ProjectEdge]:
		if not edge:
			edge = self.root
		edges = set()
		edges.add(edge)
		for dependency in edge.dependencies:
			references = self.traverse_dependencies(dependency)
			edges.update(references)
		return edges

	def get_cross_references(self, node: Optional[ProjectEdge] = None, visited: Optional[MutableSequence[ProjectEdge]] = None) -> Optional[MutableSet[tuple[ProjectEdge, ProjectEdge]]]:
		if not node:
			node = self.root
		if not visited:
			visited = list()
		if node in visited:
			cross_references = set()
			cross_references.add((visited[-1], node))
			return cross_references
		visited.append(node)
		for dependency in node.dependencies:
			cross_references = self.get_cross_references(dependency, visited)
			if cross_references:
				return cross_references
		visited.remove(node)

def collect_dependencies(config: MakeDataConfig, graph: ProjectGraph, edge: Optional[ProjectEdge] = None) -> None:
	if not edge:
		edge = graph.root
	for dependency in config.iterate_dependencies():
		edge = graph.obtain_edge(dependency)
		if isinstance(dependency, MakeDataConfig):
			collect_dependencies(dependency, graph, edge)

def resolve_dependencies(graph: ProjectGraph, edge: Optional[ProjectEdge] = None) -> MutableSet[ProjectEdge]:
	if not edge:
		edge = graph.root
	edge_unresolved_artifacts: MutableSet[ProjectEdge] = set()
	unresolved_artifacts: MutableSet[ProjectEdge] = set()
	for dependency in edge.dependencies:
		if not isinstance(dependency.project, MakeDataConfig):
			assert dependency.artifact
			dependency.artifact.fetch()
			project = dependency.artifact.as_project()
			# Ignoring unresolved projects intentionally, otherwise artifact
			# itself can throw an error if resolving required.
			if not project:
				edge_unresolved_artifacts.add(dependency)
				continue
			dependency.project = project
			collect_dependencies(project, graph, dependency)
		unresolved_artifacts.update(resolve_dependencies(graph, dependency))
	unresolved_artifacts.update(edge_unresolved_artifacts)
	for artifact_edge in edge_unresolved_artifacts:
		graph.remove_edge(artifact_edge)
	return unresolved_artifacts

def run(argv: Optional[list[str]] = None):
	if not argv or len(argv) == 0:
		argv = sys.argv
	if "--help" in argv or len(argv) <= 1:
		show_help()
		exit(0)
	if "--list" in argv:
		show_available_tasks()
		exit(0)
	if "--cli-test" in argv:
		run_test()
		exit(0)

	from time import time
	startup_millis = time()
	argv = argv[1:]

	from .parser import apply_environment_properties, parse_arguments
	from .shell import abort, debug, error, warn
	from .task import TASKS

	try:
		targets = parse_arguments(argv, TASKS, lambda name, target, callables: warn(f"* No such task: {name}."))
	except (TypeError, ValueError) as err:
		error(" ".join(argv))
		abort(cause=err)

	apply_environment_properties()

	targets, has_anything = tee(targets)
	try:
		next(has_anything)
	except StopIteration:
		debug("* No tasks to execute.")
		exit(0)

	from . import GLOBALS
	graph = ProjectGraph(GLOBALS.MAKE_CONFIG)
	collect_dependencies(GLOBALS.MAKE_CONFIG, graph)
	unresolved_artifacts = resolve_dependencies(graph)

	targets, tasks = tee(targets)
	while True:
		try:
			callable = next(tasks)
		except StopIteration:
			break
		else:
			try:
				result = callable.callable()
				if result != 0:
					abort(f"* Task {callable.name} failed with result {result}.", code=result)
			except BaseException as err:
				if isinstance(err, SystemExit):
					raise err
				from .utils import RuntimeCodeError
				if isinstance(err, RuntimeCodeError):
					abort(f"* Task {callable.name} failed with error code #{err.code}: {err}")
				abort(f"* Task {callable.name} failed with unexpected error!", cause=err)

	startup_millis = time() - startup_millis
	debug(f"* Tasks successfully completed in {startup_millis:.2f}s!")

def run_test():
	import asyncio
	from itertools import cycle
	from random import randint, random

	from prompt_toolkit import Application
	from prompt_toolkit.key_binding import KeyBindings
	from prompt_toolkit.key_binding.bindings.focus import (focus_next,
	                                                       focus_previous)
	from prompt_toolkit.keys import Keys
	from prompt_toolkit.layout import (HSplit, Layout, ScrollablePane,
	                                   ScrollOffsets, Window)
	from prompt_toolkit.widgets import Button, HorizontalLine, TextArea

	from .shell import (Debugger, Editable, Interactable, Progress, Selectable,
	                    debug, error, get_toolchain_style, info, pretty_print,
	                    warn)

	class AnimatedTask:
		def __init__(self, project, messages, frames, speed, metadatas = None):
			self.project = project
			self.messages = messages if isinstance(messages, list) else [messages]
			self.frames = cycle(frames)
			self.speed = speed
			self.content = TextArea(dont_extend_height=True, read_only=True)
			# in vscode it causes blinking from line to line
			# self.content.window.always_hide_cursor = to_filter(True)
			self.metadata = ""
			self.metadatas = metadatas if isinstance(metadatas, list) else [metadatas if metadatas else ""]
			self.description = Interactable(text=self.metadata)
			self.steps = 0
			self.offset = 0

		async def run(self):
			while True:
				if self.steps % 30 == 0:
					self.message = self.messages[self.offset]
					self.offset = self.offset + 1 if self.offset + 1 < len(self.messages) else 0
				if self.steps % 10 == 5:
					if randint(0, 10) < 3:
						self.metadata = ""
					else:
						self.metadata = self.metadatas[randint(0, len(self.metadatas) - 1)]
				self.steps += 1
				self.content.text = f"{next(self.frames)} [{self.project}] {self.message}"
				self.description.text = "   " * 2 + f"{self.metadata}"
				await asyncio.sleep(self.speed)


	task1 = AnimatedTask(
		project="Modding Tools",
		messages="Gathering libraries metadata...",
		frames=["▖", "▗", "▚","▘", "▝", "▞"],
		speed=0.15,
		metadatas=[
			"https://nernar.github.io/metadata/libraries/latest/BlockEngine.json",
			"https://nernar.github.io/metadata/libraries/latest/StorageInterface.json",
			"https://nernar.github.io/metadata/libraries/latest/Transition.json",
			"https://nernar.github.io/metadata/libraries/latest/BetterQuesting.json",
		]
	)
	task2 = AnimatedTask(
		project="Modding Tools: Block",
		messages="Transpiling TypeScript into JavaScript...",
		frames=["▀", "▄"], # XXX: works in cringe windows terminals (consoles)
		speed=0.25,
		metadatas=[
			"script/header.js",
			"script/data/BLOCK_VARIATION.js",
			"script/data/CategoryListAdapter.js",
			"script/data/SPECIAL_TYPE.js",
			"script/data/TextureSelector.js",
			"script/data/TextureSelectorListAdapter.js",
		]
	)
	task3 = AnimatedTask(
		project="Modding Tools: Dimension",
		messages="Compiling Java... 56/234 classes",
		frames=["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"],
		speed=0.15
	)
	pushing_tasks = [
		AnimatedTask(
			project="Modding Tools: Ui",
			messages="Pushing to ZBKL631...",
			frames=["◰", "◳", "◲", "◱"] if random() < 0.75 else [" ", "▏", "▎", "▍", "▋", "▊", "▉", "▊", "▋", "▍", "▎", "▏"],
			speed=random() * 0.45 + 0.05,
			metadatas=[
				"script/header.js",
				"script/data/BLOCK_VARIATION.js",
				"script/data/CategoryListAdapter.js",
				"script/data/SPECIAL_TYPE.js",
				"script/data/TextureSelector.js",
				"script/data/TextureSelectorListAdapter.js",
			]
		) for _ in range(50)
	]

	checkbox = Selectable("Subscribe to our newsletter")
	# Box cannot cover multiple components, containerify them is cringe
	whitespace = Window(height=1)
	progress = Progress("What are we doing?")
	intermediate_progress = Progress(intermediate=True)

	def do_action():
		# XXX: patch_stdout is more than 3x time slower, so (run_)in_terminal
		# is preffered (print_formatted_text uses same function)
		debug("[DEBUG] aboba")
		info("[INFO] aboba")
		warn("[WARN] aboba")
		error("[ERROR] aboba")
		pretty_print("Wow! You are wonderful!".center(55), style="class:selection")

	contents = [
		task1.content,
		task1.description,
		task2.content,
		task2.description,
		whitespace,
		Interactable("Please confirm that you are lazy:", focusable=True),
		checkbox,
		HorizontalLine(),
		Editable("What do you want?", hint="Modding Tools+ Subscription"),
		Button("Confirm", do_action),
		whitespace,
		Interactable("Don't forget to subscribe, leave comment and like our work. Money produced from those events goes to Inner Core development!"),
		Debugger(),
		whitespace,
		task3.content,
		task3.description,
		whitespace,
		progress,
		intermediate_progress,
		whitespace,
	]
	for task in pushing_tasks:
		contents += [task.content, task.description]
	root_container = ScrollablePane(
		HSplit(contents),
		scroll_offsets=ScrollOffsets(3, 3),
		display_arrows=False,
	)

	layout = Layout(root_container)
	kb = KeyBindings()

	@kb.add("c-c")
	@kb.add("<sigint>")
	def _(event):
		event.app.exit()
		raise KeyboardInterrupt()

	kb.add(Keys.Down)(focus_next)
	kb.add(Keys.Up)(focus_previous)

	async def update_progress():
		texts = ["Downloading your BIOS...", "Comparing BIOS hashes...", "Removing previous BIOS...", "Flashing BIOS..."]
		while True:
			progress.update(progress.percentage + random() / 100.0, texts[int(progress.percentage * 4)])
			if progress.percentage >= 0.99:
				progress.update(progress.percentage, "Something went terribly wrong!")
				progress.style = "class:interrupted"
				await asyncio.sleep(5)
				progress.style = ""
				progress.percentage = 0
			else:
				await asyncio.sleep(0.1)
			intermediate_progress.text = texts[int(progress.percentage * 4)]

	async def main():
		app = Application(
			layout=layout,
			style=get_toolchain_style(),
			include_default_pygments_style=False,
			key_bindings=kb,
			full_screen=False,
			mouse_support=True,
			erase_when_done=True
		)
		app.create_background_task(task1.run())
		app.create_background_task(task2.run())
		app.create_background_task(task3.run())
		for task in pushing_tasks:
			app.create_background_task(task.run())
		app.create_background_task(update_progress())
		await app.run_async()

	try:
		asyncio.run(main())
	except (KeyboardInterrupt, EOFError):
		pretty_print("Tasks stopped gracefully.")

if __name__ == "__main__":
	run_test()
