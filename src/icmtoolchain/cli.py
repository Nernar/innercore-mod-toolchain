import sys
from itertools import tee
from typing import MutableSet, Optional

from .project_graph import ProjectEdge, ProjectGraph
from .shell import pretty_print, pretty_print_attention, pretty_print_failure


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

def show_unresolved_dependencies(dependencies: MutableSet[ProjectEdge]) -> None:
	if not any(dependencies):
		return
	pretty_print_attention(f"We were unable to resolve following dependencies: {', '.join(str(dependency) for dependency in dependencies)}")

def resolve_circular_references(graph: ProjectGraph) -> bool:
	circular_reference = graph.find_circular_reference()
	if not circular_reference:
		return False
	repr_circular_references = []
	while circular_reference:
		repr_circular_references.append(f"{circular_reference[0]} -> {circular_reference[1]}")
		graph.undepend_on(circular_reference[0], circular_reference[1], keep_unused=True)
		circular_reference = graph.find_circular_reference()
	pretty_print_attention(f"Circular dependencies detected, make sure your projects are configured correctly: {', '.join(repr_circular_references)}.")
	unused_edges = graph.remove_unused_edges()
	if any(unused_edges):
		repr_unused_edges = [f"{edge}" for edge in unused_edges]
		pretty_print_failure(f"Following dependencies have been removed as there is no further connection in them to other projects: {', '.join(repr_unused_edges)}!")
		from .utils import RuntimeCodeError
		raise RuntimeCodeError(255, "Cannot build a project with unresolved dependencies!")
	return True

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
	graph.collect_dependencies(GLOBALS.MAKE_CONFIG)
	unresolved_artifacts = graph.resolve_dependencies()
	show_unresolved_dependencies(unresolved_artifacts)
	resolve_circular_references(graph)

	from .language import MakeDataConfig
	for edge in graph.traverse_dependencies():
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
