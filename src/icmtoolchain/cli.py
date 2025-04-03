import sys
from typing import Optional


def show_help():
	print("Usage: icmtoolchain [options] ... <task1> [arguments1] ...")
	print(" " * 2 + "--help: Display this message.")
	print(" " * 2 + "--list: See available tasks.")
	print("Perform commands marked with a special decorator @task.")
	print("Example: icmtoolchain selectProject --path mod1 pushEverything selectProject --path mod2 pushEverything launchApplication")

def show_available_tasks():
	from .task import TASKS
	print("All available tasks:")
	for name, task in TASKS.items():
		print(" " * 2 + name, end="")
		if task.description:
			print(": " + task.description, end="")
		print()

def run(argv: Optional[list[str]] = None):
	if not argv or len(argv) == 0:
		argv = sys.argv
	if "--help" in argv or len(argv) <= 1:
		show_help()
		exit(0)
	if "--list" in argv:
		show_available_tasks()
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

	anything_performed = False
	tasks = iter(targets)
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
			anything_performed = True

	if not anything_performed:
		debug("* No tasks to execute.")
		exit(0)

	from .task import unlock_all_tasks
	unlock_all_tasks()

	startup_millis = time() - startup_millis
	debug(f"* Tasks successfully completed in {startup_millis:.2f}s!")

# TESTS

from prompt_toolkit.layout import (BufferControl, ConditionalContainer,
                                   Container, DummyControl, DynamicContainer,
                                   FormattedTextControl, HSplit, Layout,
                                   ScrollablePane, ScrollOffsets, UIControl,
                                   Window, WindowAlign)


def simple_async_test():
	import asyncio
	from itertools import cycle
	from random import randint, random

	from prompt_toolkit import Application
	from prompt_toolkit.key_binding import KeyBindings
	from prompt_toolkit.key_binding.bindings.focus import (focus_next,
	                                                       focus_previous)
	from prompt_toolkit.keys import Keys
	from prompt_toolkit.widgets import Label, TextArea


	class AnimatedTask:
		def __init__(self, project, messages, frames, speed, metadatas = None):
			self.project = project
			self.messages = messages if isinstance(messages, list) else [messages]
			self.frames = cycle(frames)
			self.speed = speed
			self.content = TextArea(dont_extend_height=True)
			# in vscode it causes blinking from line to line
			# self.content.window.always_hide_cursor = to_filter(True)
			self.metadata = ""
			self.metadatas = metadatas if isinstance(metadatas, list) else [metadatas if metadatas else ""]
			self.description = Label(text=self.metadata)
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

	contents = [
		task1.content,
		task1.description,
		task2.content,
		task2.description,
		task3.content,
		task3.description,
	]
	for task in pushing_tasks:
		contents += [task.content, task.description]
	root_container = ScrollablePane(
		HSplit(contents), scroll_offsets=ScrollOffsets(3, 3), display_arrows=False
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

	async def main():
		app = Application(
			layout=layout,
			key_bindings=kb,
			full_screen=False,
			mouse_support=True,
			erase_when_done=True
		)
		await asyncio.gather(
			app.run_async(),
			task1.run(),
			task2.run(),
			task3.run(),
			*(task.run() for task in pushing_tasks),
		)
		# XXX: alternative way that requires toolkit eventloop
		# app.create_background_task(task1.run())
		# app.create_background_task(task2.run())
		# app.create_background_task(task3.run())
		# for task in pushing_tasks:
			# app.create_background_task(task.run())
		# await app.run_async()

	try:
		asyncio.run(main())
	except KeyboardInterrupt or EOFError:
		print("Tasks stopped gracefully.")

if __name__ == "__main__":
	simple_async_test()
