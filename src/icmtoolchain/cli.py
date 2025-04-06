import sys
from typing import Callable, List, Optional, Union

from prompt_toolkit.key_binding.key_bindings import KeyBindingsBase
from prompt_toolkit.layout.containers import WindowRenderInfo
from prompt_toolkit.layout.controls import UIContent


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

def simple_async_test():
	import asyncio
	from itertools import cycle
	from random import randint, random

	from prompt_toolkit import Application
	from prompt_toolkit.key_binding import KeyBindings
	from prompt_toolkit.key_binding.bindings.focus import (focus_next,
	                                                       focus_previous)
	from prompt_toolkit.keys import Keys
	from prompt_toolkit.widgets import (Button, CheckboxList, HorizontalLine,
	                                    ProgressBar, TextArea)


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

	contents = [
		task1.content,
		task1.description,
		task2.content,
		task2.description,
		whitespace,
		Interactable("Please confirm that you are lazy:", focusable=True),
		checkbox,
		HorizontalLine(),
		Editable("What do you want? ", hint="Modding Tools+ Subscription"),
		Button("Confirm", lambda: checkbox.interact()),
		whitespace,
		Interactable("Don't forget to subscribe, leave comment and like our work. Money produced from those events goes to Inner Core development!"),
		Debugger(),
		whitespace,
		task3.content,
		task3.description,
		whitespace,
		progress,
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
			progress.update(progress.percentage + random(), texts[int(progress.percentage / 25)])
			if progress.percentage >= 99:
				progress.update(progress.percentage, "Something went terribly wrong!")
				progress.style = "class:interrupted"
				await asyncio.sleep(5)
				progress.style = ""
				progress.percentage = 0
			else:
				await asyncio.sleep(0.1)

	async def main():
		app = Application(
			layout=layout,
			style=Style.from_dict({
				"checkbox.inactive": "fg:ansibrightblack",
				"checkbox.active": "",
				"editable.hint": "fg:ansibrightblack",
				"progress.percentage": "",
				"progress.filled": "reverse",
				"progress.unfilled": "bg:ansibrightblack",
				"progress.time-left": "",
				"paused progress.filled": "fg:ansibrightgreen",
				"interrupted progress.filled": "fg:ansibrightyellow",
				"raised progress.filled": "fg:ansibrightred",
				"margin": "",
				"debugger-overlay": "reverse",
			}),
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
	except KeyboardInterrupt or EOFError:
		print("Tasks stopped gracefully.")

# PROMPT TOOLKIT

from datetime import datetime, timedelta

from prompt_toolkit.buffer import Buffer, BufferEventHandler
from prompt_toolkit.document import Document
from prompt_toolkit.filters import (Condition, FilterOrBool, has_focus,
                                    to_filter)
from prompt_toolkit.formatted_text import (AnyFormattedText,
                                           StyleAndTextTuples,
                                           merge_formatted_text,
                                           to_formatted_text)
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (BufferControl, ConditionalMargin, Container,
                                   Dimension, FormattedTextControl, HSplit,
                                   Layout, Margin, ScrollablePane,
                                   ScrollOffsets, SearchBufferControl,
                                   UIControl, Window, WindowAlign)
from prompt_toolkit.layout.processors import (AfterInput, BeforeInput,
                                              ConditionalProcessor, Processor)
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style

# prompt-toolkit doesn't have built-in theme styling support, which can be tracked
# on pull request https://github.com/prompt-toolkit/python-prompt-toolkit/pull/1630
# PLATFORM_TEXT_DIM = "\x1b[2m"


class InteractableMargin(Margin):
	def __init__(
		self,
		has_focus: FilterOrBool = False, 
		idle_selector_text: Optional[str] = "  ",
		focused_selector_text: Optional[str] = "> ",
	):
		self.has_focus = to_filter(has_focus)
		self.idle_selector_text = idle_selector_text or "  "
		self.focused_selector_text = focused_selector_text or "> "

	def get_width(self, get_ui_content: Callable[[], UIContent]) -> int:
		return max(len(self.idle_selector_text), len(self.focused_selector_text))

	def create_margin(self, window_render_info: WindowRenderInfo, width: int, height: int) -> StyleAndTextTuples:
		focused = self.has_focus()
		return [
			(f"class:margin", self.focused_selector_text if focused else self.idle_selector_text),
			*[(f"class:margin", self.idle_selector_text) for _ in range(height - 1)]
		]

class Interactable(FormattedTextControl):
	"""
	Pure component abstraction for all toolchain interactions in console.
	"""

	def __init__(
		self,
		text: AnyFormattedText = "",
		focusable: FilterOrBool = False,
		on_interact: Optional[Callable[['Interactable'], None]] = None,
		*,
		dont_extend_height: bool = True,
		dont_extend_width: bool = False,
		align: Union[WindowAlign, Callable[[], WindowAlign]] = WindowAlign.LEFT,
		wrap_lines: FilterOrBool = True,
		show_cursor: bool = True,
		add_interact_key_bindings: bool = False,
		idle_selector_text: Optional[str] = "  ",
		focused_selector_text: Optional[str] = "> ",
	) -> None:
		self.interactable_text = text
		FormattedTextControl.__init__(
			self,
			text=self.render_text,
			focusable=focusable,
			show_cursor=show_cursor
		)

		self.has_focus = has_focus(self)
		self.window = Window(
			content=self,
			height=Dimension(min=1),
			dont_extend_height=dont_extend_height,
			dont_extend_width=dont_extend_width,
			align=align,
			wrap_lines=wrap_lines,
			left_margins=[
				ConditionalMargin(
					InteractableMargin(self.has_focus, idle_selector_text, focused_selector_text),
					self.focusable
				)
			],
			right_margins=[
				ConditionalMargin(
					InteractableMargin(False, idle_selector_text, focused_selector_text),
					self.focusable
				)
			],
		)

		if add_interact_key_bindings:
			self.add_interact_key_bindings()
		self.on_interact = on_interact

	def render_text(self) -> AnyFormattedText:
		return self.interactable_text

	def add_interact_key_bindings(self) -> None:
		if self.key_bindings is None:
			self.key_bindings = KeyBindings()
		kb = self.key_bindings

		@kb.add(Keys.Enter)
		@kb.add(" ")
		def _(event: KeyPressEvent) -> None:
			self.interact(event)

	def interact(self, event: Optional[KeyPressEvent] = None) -> None:
		if self.on_interact:
			self.on_interact(self)

	def __pt_container__(self) -> Container:
		return self.window

class Selectable(Interactable):
	"""
	Extendable switch, which have checkable state and interact ability by default.
	"""

	def __init__(
		self,
		text: AnyFormattedText = "",
		focusable: FilterOrBool = True,
		on_checked: Optional[Callable[['Selectable', bool], None]] = None,
		checked: bool = False,
		*,
		dont_extend_height: bool = True,
		dont_extend_width: bool = False,
		align: Union[WindowAlign, Callable[[], WindowAlign]] = WindowAlign.LEFT,
		wrap_lines: FilterOrBool = True,
		show_cursor: bool = False,
		add_interact_key_bindings: bool = True,
		on_interact: Optional[Callable[['Interactable'], None]] = None,
		idle_selector_text: Optional[str] = "  ",
		focused_selector_text: Optional[str] = "> ",
		unchecked_checkbox_text: Optional[str] = "[ ] ",
		checked_checkbox_text: Optional[str] = "[x] ",
	) -> None:
		Interactable.__init__(
			self,
			text=text,
			focusable=focusable,
			on_interact=on_interact,
			dont_extend_height=dont_extend_height,
			dont_extend_width=dont_extend_width,
			align=align,
			wrap_lines=wrap_lines,
			show_cursor=show_cursor,
			add_interact_key_bindings=add_interact_key_bindings,
			idle_selector_text=idle_selector_text,
			focused_selector_text=focused_selector_text,
		)

		self.checked = checked
		self.on_checked = on_checked
		self.unchecked_checkbox_text = unchecked_checkbox_text or "[ ] "
		self.checked_checkbox_text = checked_checkbox_text or "[x] "

	def render_checkbox(self) -> AnyFormattedText:
		return [
			("class:checkbox.active", self.checked_checkbox_text) if self.checked \
				else ("class:checkbox.inactive", self.unchecked_checkbox_text)
		]

	def render_text(self) -> AnyFormattedText:
		text = Interactable.render_text(self)
		return merge_formatted_text((
			to_formatted_text(self.render_checkbox(), self.style),
			to_formatted_text(text, self.style),
		))

	def interact(self, event: Optional[KeyPressEvent] = None) -> None:
		self.checked = not self.checked
		Interactable.interact(self, event)

class Editable(BufferControl):
	"""
	Editable area, text can be written when input become focused, supports prompt, placeholder, etc.
	"""

	def __init__(
		self,
		prompt: AnyFormattedText = None,
		text: str = "",
		multiline: FilterOrBool = False,
		focusable: FilterOrBool = True,
		*,
		hint: Optional[str] = None,
		use_hint_as_fallback: bool = True,
		read_only: FilterOrBool = False,
        on_text_changed: Optional[BufferEventHandler] = None,
		dont_extend_height: bool = True,
		dont_extend_width: bool = False,
		align: Union[WindowAlign, Callable[[], WindowAlign]] = WindowAlign.LEFT,
		wrap_lines: FilterOrBool = True,
		input_processors: Optional[List[Processor]] = None,
		include_default_input_processors: bool = True,
		lexer: Optional[Lexer] = None,
		preview_search: FilterOrBool = False,
		search_buffer_control: Optional[Union[SearchBufferControl, Callable[[], SearchBufferControl]]] = None,
		menu_position: Optional[Callable[[], Optional[int]]] = None,
		add_interact_key_bindings: bool = True,
		on_interact: Optional[Callable[['Editable'], None]] = None,
		idle_selector_text: Optional[str] = "  ",
		focused_selector_text: Optional[str] = "> ",
		focus_on_click: FilterOrBool = True,
	) -> None:
		buffer = Buffer(
			document=Document(text),
			read_only=read_only,
			# TODO: Handle arrows cursor movement for multine
			multiline=multiline,
			on_text_changed=on_text_changed,
		)
		BufferControl.__init__(
			self,
			buffer=buffer,
			input_processors=input_processors,
			include_default_input_processors=include_default_input_processors,
			lexer=lexer,
			preview_search=preview_search,
			focusable=focusable,
			search_buffer_control=search_buffer_control,
			menu_position=menu_position,
			focus_on_click=focus_on_click,
		)

		self.has_focus = has_focus(self)
		self.window = Window(
			content=self,
			height=Dimension(min=1),
			dont_extend_height=dont_extend_height,
			dont_extend_width=dont_extend_width,
			align=align,
			wrap_lines=wrap_lines,
			left_margins=[
				ConditionalMargin(
					InteractableMargin(self.has_focus, idle_selector_text, focused_selector_text),
					self.focusable
				)
			],
			right_margins=[
				ConditionalMargin(
					InteractableMargin(False, idle_selector_text, focused_selector_text),
					self.focusable
				)
			],
		)

		self.style = ""
		self.prompt = prompt
		self.hint = hint
		self.use_hint_as_fallback = use_hint_as_fallback

		if not self.input_processors:
			self.input_processors = []
		self.input_processors.extend((
			ConditionalProcessor(
				BeforeInput(lambda: self.prompt),
				Condition(self.has_prompt)
			),
			ConditionalProcessor(
				AfterInput(lambda: [("class:editable.hint", self.hint)]),
				Condition(self.has_hint)
			),
		))

		if add_interact_key_bindings:
			self.add_interact_key_bindings()
		self.on_interact = on_interact

	def has_prompt(self) -> bool:
		return self.prompt is not None and len(to_formatted_text(self.prompt, self.style)) > 0

	def has_hint(self) -> bool:
		return self.hint is not None and len(self.buffer.text) == 0 and len(self.hint) > 0

	def is_interactable(self) -> bool:
		return not self.buffer.multiline() or len(self.buffer.text) == 0

	def add_interact_key_bindings(self) -> None:
		if self.key_bindings is None:
			self.key_bindings = KeyBindings()
		kb = self.key_bindings

		@kb.add(Keys.Enter, filter=Condition(self.is_interactable))
		def _(event: KeyPressEvent) -> None:
			self.interact(event)

	def interact(self, event: Optional[KeyPressEvent] = None) -> None:
		if self.on_interact:
			self.on_interact(self)
		if self.use_hint_as_fallback and not self.buffer.read_only() and self.has_hint():
			self.buffer.document = Document(self.hint or "...")

	def __pt_container__(self) -> Container:
		return self.window

def format_timedelta(timedelta: timedelta) -> str:
    result = f"{timedelta}".split(".")[0]
    if result.startswith("0:"):
        result = result[2:]
    return result

class Progress(UIControl):
	"""
	Percentage bar with left time and interaction ability.
	"""

	def __init__(
		self,
		text: Optional[str] = None,
		focusable: FilterOrBool = False,
		on_interact: Optional[Callable[['Progress'], None]] = None,
		*,
		dont_extend_height: bool = True,
		dont_extend_width: bool = False,
		align: Union[WindowAlign, Callable[[], WindowAlign]] = WindowAlign.LEFT,
		wrap_lines: FilterOrBool = True,
		add_interact_key_bindings: bool = False,
		idle_selector_text: Optional[str] = "  ",
		focused_selector_text: Optional[str] = "> ",
	):
		self.done = False
		self.start_time = datetime.now()
		self.stopped = False
		self.stop_time = None
		self.percentage = 0.0
		self.text = text

		self.focusable = to_filter(focusable)
		self.has_focus = has_focus(self)
		self.window = Window(
			content=self,
			height=Dimension(min=1),
			dont_extend_height=dont_extend_height,
			dont_extend_width=dont_extend_width,
			align=align,
			wrap_lines=wrap_lines,
			left_margins=[
				ConditionalMargin(
					InteractableMargin(self.has_focus, idle_selector_text, focused_selector_text),
					self.focusable
				)
			],
			right_margins=[
				ConditionalMargin(
					InteractableMargin(False, idle_selector_text, focused_selector_text),
					self.focusable
				)
			],
		)

		self.style = ""
		self.key_bindings = None
		if add_interact_key_bindings:
			self.add_interact_key_bindings()
		self.on_interact = on_interact

	def is_focusable(self) -> bool:
		return self.focusable()

	def add_interact_key_bindings(self) -> None:
		if self.key_bindings is None:
			self.key_bindings = KeyBindings()
		kb = self.key_bindings

		@kb.add(Keys.Enter)
		@kb.add(" ")
		def _(event: KeyPressEvent) -> None:
			self.interact(event)

	def interact(self, event: Optional[KeyPressEvent] = None) -> None:
		if self.on_interact:
			self.on_interact(self)

	def get_key_bindings(self) -> Optional[KeyBindingsBase]:
		return self.key_bindings

	def render_progress(self, offset: int, width: int) -> AnyFormattedText:
		time_left = self.time_left()
		percentage_text = f"{self.percentage:.1f}% "
		time_left_text = f" {format_timedelta(time_left) if time_left else 'N/A'}"

		available_width = width - len(percentage_text) - len(time_left_text)
		filled_progress_width = int(self.percentage / 100 * available_width)
		bar_text = self.text.center(available_width) if self.text else " " * available_width

		return [
			("class:progress.percentage", percentage_text),
			("class:progress.filled", bar_text[:filled_progress_width]),
			("class:progress.unfilled", bar_text[filled_progress_width:]),
			("class:progress.time-left", time_left_text),
		]

	def create_content(self, width: int, height: int) -> UIContent:
		return UIContent(
			get_line=lambda offset: to_formatted_text(
				self.render_progress(offset, width),
				self.style
			),
			line_count=1,
			show_cursor=False
		)

	def update(self, percentage: float, text: Optional[str] = None) -> None:
		self.percentage = max(0, min(100, percentage))
		if text is not None:
			self.text = text

	def time_elapsed(self) -> timedelta:
		if self.stop_time is None:
			return datetime.now() - self.start_time
		else:
			return self.stop_time - self.start_time

	def time_left(self) -> Optional[timedelta]:
		if not self.percentage:
			return None
		elif self.done or self.stopped:
			return timedelta(0)
		else:
			return self.time_elapsed() * (100 - self.percentage) / self.percentage

	def __pt_container__(self) -> Container:
		return self.window

class Debugger(Interactable):
	"""
	Debugging staff considered from content with max available width. 
	"""

	def __init__(
		self,
		*,
		align: Union[WindowAlign, Callable[[], WindowAlign]] = WindowAlign.LEFT,
	) -> None:
		Interactable.__init__(
			self,
			text="N/A",
			focusable=False,
			dont_extend_height=True,
			dont_extend_width=True,
			align=align,
			wrap_lines=False,
		)

	def preferred_width(self, max_available_width: int) -> int:
		self._max_available_width = max_available_width
		return super().preferred_width(max_available_width)

	def render_text(self) -> AnyFormattedText:
		from prompt_toolkit.application import get_app
		app = get_app()
		screen = app.renderer.last_rendered_screen
		max_available_width = 0
		if hasattr(self, "_max_available_width"):
			max_available_width = self._max_available_width
		if max_available_width <= 0 and screen is not None:
			max_available_width = screen.width
		if max_available_width <= 0:
			return super().render_text()
		buffer = []
		if screen is not None:
			buffer.append(f"{screen.width}x{screen.height}{'f' if screen.show_cursor else 'h'}")
		buffer.append(f"{app.color_depth.value.split('_', 3)[1]}d/")
		current_buffer = app.layout.current_buffer
		if current_buffer is not None:
			buffer.append(f"{len(current_buffer.text)}b")
		current_control = app.layout.current_control
		if current_control is not None:
			buffer.append(current_control.__class__.__name__)
		current_window = app.layout.current_window
		if current_window is not None:
			render_info = current_window.render_info
			if render_info is not None:
				buffer.append(f"{render_info.window_width}x{render_info.window_height}{'n' if render_info.wrap_lines else 's'}")
		if current_buffer is None and current_control is None and current_window is None:
			buffer.append("inactive")
		buffer.append(f"/{sum(1 for _ in app.layout.find_all_controls())}c")
		buffer.append(f"{len(app.layout.visible_windows)}vw")
		buffer.append(f"{sum(1 for _ in app.layout.find_all_windows())}w")
		text = " " + "".join(buffer) + " "
		if len(text) > self._max_available_width:
			text = text[:self._max_available_width - 2] + "+ "
		return [
			("class:debugger-overlay", text.center(self._max_available_width, "▄").replace("▄▄", "▄▀")),
		]

if __name__ == "__main__":
	simple_async_test()
