from datetime import datetime, timedelta
from io import StringIO
from typing import (Any, Callable, Dict, List, Literal, NoReturn, Optional,
                    Sequence, Tuple, Union, cast, overload)

from prompt_toolkit import Application, print_formatted_text
from prompt_toolkit.buffer import Buffer, BufferEventHandler
from prompt_toolkit.document import Document
from prompt_toolkit.filters import (Condition, FilterOrBool, has_focus,
                                    to_filter)
from prompt_toolkit.formatted_text import (AnyFormattedText, FormattedText,
                                           StyleAndTextTuples,
                                           merge_formatted_text,
                                           to_formatted_text)
from prompt_toolkit.key_binding import (KeyBindings, KeyBindingsBase,
                                        KeyPressEvent)
from prompt_toolkit.key_binding.bindings.focus import (focus_next,
                                                       focus_previous)
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (AnyContainer, BufferControl,
                                   ConditionalMargin, Container, Dimension,
                                   FormattedTextControl, HSplit, Layout,
                                   Margin, ScrollablePane, ScrollOffsets,
                                   SearchBufferControl, UIContent, UIControl,
                                   VerticalAlign, Window, WindowAlign,
                                   WindowRenderInfo)
from prompt_toolkit.layout.processors import (AfterInput, BeforeInput,
                                              ConditionalProcessor, Processor)
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import SetDefaultColorStyleTransformation, Style

# prompt-toolkit doesn't have built-in theme styling support, which can be tracked
# on pull request https://github.com/prompt-toolkit/python-prompt-toolkit/pull/1630
# TOOLCHAIN_ANSI_DIM = "\x1b[2m"

TOOLCHAIN_STYLE = {
	# prompt-toolkit overrides
	"scrollbar.background": "bg:ansibrightblack",
	"scrollbar.button": "bg:ansiwhite",

	# logging and tty styling
	"selection": "reverse",
	"task.execute": "fg:ansibrightgreen bold",
	"print.answer": "fg:ansibrightblack",
	"print.debug": "fg:ansibrightblack",
	"print.info": "fg:ansibrightgreen",
	"print.warn": "fg:ansibrightyellow",
	"print.error": "fg:ansibrightred",
	"print.abort-message": "fg:ansibrightred bold",

	# interactables styling
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
}

def get_toolchain_style() -> Style:
	return Style.from_dict(TOOLCHAIN_STYLE)

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
		style: str = "",
		dont_extend_height: bool = True,
		dont_extend_width: bool = False,
		align: Union[WindowAlign, Callable[[], WindowAlign]] = WindowAlign.LEFT,
		wrap_lines: FilterOrBool = True,
		show_cursor: bool = True,
		add_interact_key_bindings: bool = False,
		idle_selector_text: Optional[str] = "  ",
		focused_selector_text: Optional[str] = "> ",
		tag: object = None,
	) -> None:
		self.interactable_text = text
		FormattedTextControl.__init__(
			self,
			text=self.render_text,
			style=style,
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
		self.tag = tag

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
		style: str = "",
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
		tag: object = None,
	) -> None:
		Interactable.__init__(
			self,
			text=text,
			focusable=focusable,
			on_interact=on_interact,
			style=style,
			dont_extend_height=dont_extend_height,
			dont_extend_width=dont_extend_width,
			align=align,
			wrap_lines=wrap_lines,
			show_cursor=show_cursor,
			add_interact_key_bindings=add_interact_key_bindings,
			idle_selector_text=idle_selector_text,
			focused_selector_text=focused_selector_text,
			tag=tag,
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
		style: str = "",
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
		tag: object = None,
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

		self.style = style
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
		self.tag = tag

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
		style: str = "",
		dont_extend_height: bool = True,
		dont_extend_width: bool = False,
		align: Union[WindowAlign, Callable[[], WindowAlign]] = WindowAlign.LEFT,
		wrap_lines: FilterOrBool = True,
		add_interact_key_bindings: bool = False,
		idle_selector_text: Optional[str] = "  ",
		focused_selector_text: Optional[str] = "> ",
		tag: object = None,
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

		self.style = style
		self.key_bindings = None
		if add_interact_key_bindings:
			self.add_interact_key_bindings()
		self.on_interact = on_interact
		self.tag = tag

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
		tag: object = None,
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


def select_prompt_internal(prompt: Optional[str] = None, *variants: str, text_transformer: Optional[Callable[[str, int], AnyFormattedText]] = None, fallback: Optional[int] = None) -> Tuple[Optional[int], Optional[Any]]:
	immutable_variants = list(variants)
	assert fallback is None or fallback >= 0
	choice_variants: Sequence[AnyContainer] = []
	which_offset = 0
	for variant in immutable_variants:
		text = text_transformer(variant, which_offset) if text_transformer else variant
		choice_variants.append(
			Interactable(text, focusable=True, show_cursor=False, tag=which_offset)
		)
		which_offset += 1

	bindings = KeyBindings()
	bindings.add(Keys.Down)(focus_next)
	bindings.add(Keys.Up)(focus_previous)

	@bindings.add(Keys.Enter)
	@bindings.add(" ")
	def _(event: KeyPressEvent) -> None:
		event.app.layout.current_control
		event.app.exit()

	@bindings.add("c-c")
	@bindings.add("<sigint>")
	def _(event: KeyPressEvent) -> NoReturn:
		event.app.exit()
		raise KeyboardInterrupt()

	choice_container = ScrollablePane(
		HSplit(choice_variants),
		scroll_offsets=ScrollOffsets(3, 3),
		display_arrows=False,
	)
	contents: Sequence[AnyContainer] = []
	if prompt:
		contents.append(Interactable(prompt))
	contents.append(choice_container)
	app = Application(
		layout=Layout(HSplit(contents)),
		style=get_toolchain_style(),
		include_default_pygments_style=False,
		key_bindings=bindings,
		full_screen=False,
		mouse_support=True,
		erase_when_done=True,
	)

	try:
		app.run()
		control = app.layout.current_control
		assert isinstance(control, Interactable)
		which = cast(int, control.tag)
	except KeyboardInterrupt or EOFError:
		which = fallback

	what = None
	if which is not None:
		what = immutable_variants[which]
	if what is not None:
		pretty_print_answer(prompt, what)

	return which, what

@overload
def select_prompt(prompt: Optional[str] = None, *variants: str, text_transformer: Optional[Callable[[str, int], AnyFormattedText]] = None, fallback: Optional[int] = None, returns_what: Literal[False] = False) -> Optional[int]: ...
@overload
def select_prompt(prompt: Optional[str] = None, *variants: str, text_transformer: Optional[Callable[[str, int], AnyFormattedText]] = None, fallback: Optional[int] = None, returns_what: Literal[True] = True) -> Optional[str]: ...

def select_prompt(prompt: Optional[str] = None, *variants: str, text_transformer: Optional[Callable[[str, int], AnyFormattedText]] = None, fallback: Optional[int] = None, returns_what: bool = False) -> Optional[Union[str, int]]:
	return select_prompt_internal(prompt, *variants, text_transformer=text_transformer, fallback=fallback)[1 if returns_what else 0]

def confirm(prompt: str, fallback: bool, prints_abort: bool = True) -> bool:
	try:
		if input(prompt + (" [Y/n] " if fallback else " [N/y] ")).lower()[:1] == ("n" if fallback else "y"):
			if prints_abort and fallback:
				pretty_print("Abort.")
			return not fallback
	except KeyboardInterrupt:
		pretty_print()
	if prints_abort and not fallback:
		pretty_print("Abort.")
	return fallback

def stringify(*values: object, sep: Optional[str] = " ", end: Optional[str] = "") -> str:
	buffer = StringIO()
	print(*values, sep=sep, end=end, file=buffer)
	return buffer.getvalue()

def link(text: str, url: Optional[str] = None) -> str:
	return f"\x1b]8;;{url or text}\a{text}\x1b]8;;\a"

def image(base64: str, options: Optional[Dict[str, object]] = None) -> str:
	returnValue = "\x1b]1337;File=inline=1"
	if options:
		if "width" in options:
			returnValue += ";width=" + str(options["width"])
		if "height" in options:
			returnValue += ";height=" + str(options["height"])
		if "preserveAspectRatio" in options and options["preserveAspectRatio"] == False:
			returnValue += ";preserveAspectRatio=0"
	return f"{returnValue}:{base64}\a"

def pretty_print(*values: object, style: str = "", sep: Optional[str] = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	print_formatted_text(to_formatted_text(stringify(*values, sep=sep), style=style), end=end or "\n", file=file, flush=flush, style=get_toolchain_style(), include_default_pygments_style=include_default_pygments_style)

def debug(*values: object, sep: Optional[str] = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	pretty_print(*values, sep=sep, end=end, file=file, flush=flush, style="class:print.debug", include_default_pygments_style=include_default_pygments_style)

def info(*values: object, sep: Optional[str] = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	pretty_print(*values, sep=sep, end=end, file=file, flush=flush, style="class:print.info", include_default_pygments_style=include_default_pygments_style)

def warn(*values: object, sep: Optional[str] = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	pretty_print(*values, sep=sep, end=end, file=file, flush=flush, style="class:print.warn", include_default_pygments_style=include_default_pygments_style)

def error(*values: object, sep: Optional[str] = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	pretty_print(*values, sep=sep, end=end, file=file, flush=flush, style="class:print.error", include_default_pygments_style=include_default_pygments_style)

def pretty_print_answer(prompt: AnyFormattedText, *values: object, sep: str=", ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	if prompt:
		pretty_print(prompt, end=" ", file=file, flush=flush, include_default_pygments_style=include_default_pygments_style)
	pretty_print(*values, style="class:print.answer", sep=sep, end=end, file=file, flush=flush, include_default_pygments_style=include_default_pygments_style)

def abort(*values: object, sep: Optional[str] = " ", code: int = 255, cause: Optional[BaseException] = None) -> NoReturn:
	if cause:
		from traceback import print_exception
		buffer = StringIO()
		print_exception(cause.__class__, cause, cause.__traceback__, file=buffer)
		error(buffer.getvalue().rsplit("\n", 9)[1:-1], sep="\n")
	if len(values) != 0:
		pretty_print(*values, sep=sep, style="class:print.abort-message")
	elif not cause:
		pretty_print("Abort.")
	try:
		from .task import unlock_all_tasks
		unlock_all_tasks()
	except IOError:
		pass
	exit(code)
